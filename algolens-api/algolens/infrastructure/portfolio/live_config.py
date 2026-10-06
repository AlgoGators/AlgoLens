"""Atomic candidates/activation under current authority → source → book → config locks."""
from contextlib import contextmanager
import json
import psycopg2
from psycopg2.extras import Json, RealDictCursor
from algolens.application.live_config import LiveConfigError, resolve_person
from algolens.infrastructure.db.postgres import get_db_connection
from algolens.infrastructure.portfolio.qt_authorization import lock_current_authorities


def _dto(row):
    fields = ('version_id','registry_id','portfolio_id','engine_strategy_id','registry_revision',
              'validator_build','validator_sha256','base_sha256','effective_sha256','operation',
              'changes','previous_version_id','submitted_by','submitter_person_id','reason')
    return {**{k: row[k] for k in fields}, 'submitted_at':row['submitted_at'].isoformat()}


def _equal(left, right):
    # Exact values and numeric types; never use this serialization for hashes.
    return json.dumps(left, sort_keys=True, allow_nan=False) == json.dumps(right, sort_keys=True, allow_nan=False)


class PostgresLiveConfigRepository:
    def __init__(self, connection_factory=None):
        self.connection_factory = connection_factory or get_db_connection

    @contextmanager
    def transaction(self):
        conn = None
        try:
            conn = self.connection_factory()
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                yield cursor
            conn.commit()
        except Exception as exc:
            if conn is not None:
                conn.rollback()
            if isinstance(exc, psycopg2.Error):
                # Never expose SQL diagnostics or arbitrary native stderr.
                code = 'live_config_active_changed' if 'live_config_active_changed' in str(exc) else 'live_config_storage_unavailable'
                raise LiveConfigError(code, 409 if code.endswith('changed') else 503) from None
            raise
        finally:
            if conn is not None:
                conn.close()

    @staticmethod
    def scope(cursor, provision, *, eligible=True):
        wanted = provision['scope']
        cursor.execute('SELECT trading.lock_live_config_scope(%s,%s) AS scope',
                       (wanted['engine_strategy_id'],wanted['portfolio_id']))
        scope = cursor.fetchone()['scope']
        if scope['registry_id'] != wanted['registry_id'] or scope['investor_book_id'] is not None:
            raise LiveConfigError('live_config_scope_unsupported')
        cursor.execute('SELECT lifecycle,is_active FROM trading.strategy_registry WHERE id=%s', (scope['registry_id'],))
        registry = cursor.fetchone()
        if eligible and (registry['is_active'] is not True or registry['lifecycle'] not in ('live','incubating')):
            raise LiveConfigError('live_config_scope_unsupported')
        return scope

    @staticmethod
    def active(cursor, scope):
        cursor.execute('''SELECT v.*, a.version_id AS pointer_version_id, audit.version_id AS activation_version_id
            FROM trading.live_config_active a
            LEFT JOIN trading.live_config_versions v ON v.version_id=a.version_id
            LEFT JOIN trading.live_config_activations audit ON audit.version_id=a.version_id
            WHERE a.registry_id=%s AND a.portfolio_id=%s AND a.engine_strategy_id=%s''',
            (scope['registry_id'],scope['portfolio_id'],scope['engine_strategy_id']))
        row = cursor.fetchone()
        if row is not None and (row['version_id'] != row['pointer_version_id']
                or row['version_id'] != row['activation_version_id']
                or any(row[key] != scope[key] for key in ('registry_id','portfolio_id','engine_strategy_id'))
                or row['operation'] not in ('override','reset_to_baseline')):
            raise LiveConfigError('live_config_configuration_changed')
        return row

    @staticmethod
    def expected(active, expected):
        if (str(active['version_id']) if active else None) != expected:
            raise LiveConfigError('live_config_active_changed')

    @staticmethod
    def replay(config, provision, scope, row):
        pin = provision['pin']
        if (row['registry_revision'] != scope['registry_revision'] or row['validator_build'] != pin['build']
                or row['validator_sha256'] != pin['bundle_sha256']):
            raise LiveConfigError('live_config_configuration_changed')
        result = config.validate(provision,row['changes'],row['operation'])
        if any(not _equal(row[k],result[k]) for k in ('base_sha256','effective_sha256','effective_snapshot')):
            raise LiveConfigError('live_config_configuration_changed')
        return result

    def candidate(self, strategy_id, body, user_id, config, *, persist):
        with self.transaction() as cur:
            authority = lock_current_authorities(cur,[user_id])
            person = resolve_person(user_id,authority[user_id],'config_submit')
            provision = config.load(strategy_id,body['portfolio_id'])
            scope = self.scope(cur,provision)
            self.expected(self.active(cur,scope),body['expected_active_version'])
            result = config.validate(provision,body['changes'],body['operation'])
            config.recheck(provision)
            if not persist:
                return {**result,'operation':body['operation'],'expected_active_version':body['expected_active_version'],
                        'execution_authorized':False}
            cur.execute('''INSERT INTO trading.live_config_versions
              (registry_id,portfolio_id,engine_strategy_id,registry_revision,validator_build,validator_sha256,
               base_sha256,effective_sha256,changes,effective_snapshot,previous_version_id,
               submitted_by,submitter_person_id,reason,operation,submission_authority)
              VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *''',
              (strategy_id,scope['portfolio_id'],scope['engine_strategy_id'],scope['registry_revision'],
               provision['pin']['build'],provision['pin']['bundle_sha256'],result['base_sha256'],result['effective_sha256'],
               Json(body['changes']),Json(result['effective_snapshot']),body['expected_active_version'],
               str(user_id),person['person_id'],body['reason'],body['operation'],Json(person)))
            return {**_dto(cur.fetchone()),'execution_authorized':False}

    def approve(self, strategy_id, request_id, body, user_id, config):
        with self.transaction() as cur:
            # Immutable candidate can be read before locking, solely to locate both actors.
            cur.execute('SELECT * FROM trading.live_config_versions WHERE version_id=%s AND registry_id=%s AND portfolio_id=%s',
                        (request_id,strategy_id,body['portfolio_id']))
            row = cur.fetchone()
            if row is None:
                raise LiveConfigError('live_config_request_not_found',404)
            try:
                submitter_id = int(row['submitted_by'])
            except (ValueError,TypeError):
                raise LiveConfigError('live_config_authorization_changed',403) from None
            authorities = lock_current_authorities(cur,[user_id,submitter_id])
            submitter = resolve_person(submitter_id,authorities[submitter_id],'config_submit')
            if row.get('submission_authority') != submitter:
                raise LiveConfigError('live_config_authorization_changed',403)
            approver = resolve_person(user_id,authorities[user_id],'config_approve')
            if (submitter['person_id'] != row['submitter_person_id'] or
                    submitter['person_id'] == approver['person_id'] or user_id == submitter_id):
                raise LiveConfigError('live_config_distinct_person_required',403)
            provision = config.load(strategy_id,body['portfolio_id'])
            scope = self.scope(cur,provision)
            self.expected(self.active(cur,scope),body['expected_active_version'])
            if row['previous_version_id'] != body['expected_active_version']:
                raise LiveConfigError('live_config_active_changed')
            self.replay(config,provision,scope,row)
            config.recheck(provision)
            cur.execute('''INSERT INTO trading.live_config_activations
              (version_id,approved_by,approver_person_id,authority_versions,reason)
              VALUES (%s,%s,%s,%s,%s) RETURNING activation_id,activated_at''',
              (request_id,str(user_id),approver['person_id'],Json({'submitter':submitter,'approver':approver}),body['reason']))
            audit = cur.fetchone()
            return {**_dto(row),'activation_id':audit['activation_id'],'activated_at':audit['activated_at'].isoformat(),
                    'execution_authorized':False}

    def selected_scope(self, strategy_id, book, config, *, cursor=None, eligible=False):
        if cursor is None:
            with self.transaction() as cur:
                return self.selected_scope(strategy_id,book,config,cursor=cur,eligible=eligible)
        provision = config.load(strategy_id,book)
        scope = self.scope(cursor,provision,eligible=eligible)
        active = self.active(cursor,scope)
        result = (self.replay(config,provision,scope,active) if active else
                  config.validate(provision,{},'reset_to_baseline'))
        config.recheck(provision)
        return {**provision['scope'],'config_snapshot':result['effective_snapshot']}

    def status(self, strategy_id, book, config):
        with self.transaction() as cur:
            provision = config.load(strategy_id,book)
            scope = self.scope(cur,provision,eligible=False)
            active = self.active(cur,scope)
            if active:
                self.replay(config,provision,scope,active)
            else:
                config.validate(provision,{},'reset_to_baseline')
            config.recheck(provision)
            cur.execute('SELECT * FROM trading.live_config_versions WHERE registry_id=%s AND portfolio_id=%s '
                        'ORDER BY submitted_at DESC LIMIT 25',(strategy_id,book))
            return {'active':_dto(active) if active else None,'requests':[_dto(row) for row in cur.fetchall()],
                    'execution_authorized':False,
                    'reset_semantics':'reset_to_baseline restores current baseline values as an approved version; later file or build drift requires a new approval.'}
