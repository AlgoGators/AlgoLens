"""One read-only PostgreSQL snapshot for a selected book's publication."""

from algolens.application.configuration_inspection import InspectionError
from algolens.domain.portfolio.configuration_inspection import MAX_DOCUMENT_BYTES, PublicationError
from algolens.domain.portfolio.equity_configuration_inspection import parse_publication
from algolens.domain.portfolio.portfolio_assignment import match_book
from algolens.infrastructure.db.postgres import get_db_connection


class PostgresConfigurationInspectionReader:
    def __init__(self, connection_factory=None):
        self.connection_factory = connection_factory or get_db_connection

    def read(self, registry_id, portfolio_id, read_at):
        conn = None
        try:
            conn = self.connection_factory()
            conn.set_session(readonly=True, isolation_level="REPEATABLE READ")
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, strategy_type, portfolio_id, runtime_revision
                    FROM trading.strategy_registry WHERE id = %s
                """, (registry_id,))
                registry = cur.fetchone()
                if registry is None:
                    raise InspectionError("strategy_not_found", 404)

                # A failed membership read is a storage failure. Primary fallback
                # applies only to a successful query with zero membership rows.
                cur.execute("""
                    SELECT portfolio_id FROM trading.strategy_book_memberships
                    WHERE strategy_id = %s ORDER BY portfolio_id
                """, (registry_id,))
                books = [row["portfolio_id"] for row in cur.fetchall()]
                if not books:
                    books = [registry["portfolio_id"]]
                selected_book = match_book(portfolio_id, books)
                if selected_book is None:
                    raise InspectionError("not_a_member_of_book", 400)

                # CASE prevents an oversized reserved child from crossing the
                # database/client boundary. The parent and other child keys are
                # never selected. LIMIT is after date ordering, never validity.
                cur.execute("""
                    SELECT date, strategy_id, portfolio_id,
                           octet_length((portfolio_config -> 'config_inspection')::text) AS child_bytes,
                           CASE WHEN octet_length((portfolio_config -> 'config_inspection')::text) <= %s
                                THEN (portfolio_config -> 'config_inspection')::text
                                ELSE NULL END AS child_text
                    FROM trading.live_run_metadata
                    WHERE strategy_id = %s AND portfolio_id = %s
                    ORDER BY date DESC LIMIT 1
                """, (MAX_DOCUMENT_BYTES, registry["strategy_type"], selected_book))
                metadata = cur.fetchone()

                cur.execute("""
                    SELECT (date AT TIME ZONE 'UTC')::date AS run_date
                    FROM trading.live_results
                    WHERE strategy_id = %s AND portfolio_id = %s AND portfolio_type = %s
                    ORDER BY date DESC LIMIT 1
                """, (registry["strategy_type"], selected_book, "system"))
                result = cur.fetchone()

                # Even an uncontrolled envelope requires the runtime schema to
                # exist; legacy stores do not imply an invented publication.
                cur.execute("""
                    SELECT a.id, i.id FROM trading.runtime_attempts a
                    JOIN trading.runtime_intents i ON i.id = a.intent_id LIMIT 0
                """)

                if metadata is None:
                    outcome = ("unavailable", "not_published", selected_book)
                elif metadata["child_bytes"] is None:
                    outcome = ("unavailable", "legacy_publication", selected_book)
                elif metadata["child_bytes"] > MAX_DOCUMENT_BYTES or metadata["child_text"] is None:
                    outcome = ("unavailable", "invalid_publication", selected_book)
                elif result is None or metadata["date"] != result["run_date"]:
                    outcome = ("unavailable", "publication_date_mismatch", selected_book)
                else:
                    scope = {"registry_id": registry["id"],
                             "registry_revision": registry["runtime_revision"],
                             "engine_strategy_id": registry["strategy_type"],
                             "portfolio_id": selected_book,
                             "run_date": metadata["date"].isoformat()}
                    try:
                        publication = parse_publication(metadata["child_text"], scope, read_at)
                    except PublicationError as exc:
                        outcome = ("unavailable", exc.reason, selected_book)
                    else:
                        identity = publication["identity"]
                        if publication["publication_schema_version"] in (4,5):
                            cur.execute("""
                                SELECT a.attempt_id,a.portfolio_id,a.engine_strategy_id,a.run_date,
                                       a.engine_build,a.selection,a.config_snapshot,
                                       s.classification_version,s.state,s.lifecycle,s.publication_id AS sealed_publication_id
                                FROM trading.live_config_attempt_selections a
                                JOIN trading.live_config_attempt_safety s USING(attempt_id)
                                WHERE a.attempt_id=%s
                            """, (identity["config_attempt_id"],))
                            if not self._config_attempt_matches(cur.fetchone(),publication):
                                outcome=("unavailable","invalid_publication",selected_book)
                                conn.commit()
                                return outcome
                        if identity["control_mode"] == "controlled":
                            cur.execute("""
                                SELECT a.id AS attempt_id, a.registry_revision AS attempt_revision,
                                       a.run_date AS attempt_run_date, a.status AS attempt_status,
                                       a.outcome AS attempt_outcome, a.publication_id AS attempt_publication_id,
                                       i.registry_id AS intent_registry_id,
                                       i.registry_revision AS intent_revision,
                                       i.engine_strategy_id AS intent_engine_id,
                                       i.portfolio_id AS intent_portfolio_id,
                                       i.action AS intent_action
                                FROM trading.runtime_attempts a
                                JOIN trading.runtime_intents i ON i.id = a.intent_id
                                WHERE a.id = %s
                            """, (identity["runtime_attempt_id"],))
                            attempt = cur.fetchone()
                            if not self._attempt_matches(attempt, identity):
                                outcome = ("unavailable", "invalid_publication", selected_book)
                            else:
                                outcome = (publication["status"], publication, selected_book)
                        else:
                            outcome = (publication["status"], publication, selected_book)
            conn.commit()
            return outcome
        except InspectionError:
            if conn is not None:
                conn.rollback()
            raise
        except Exception:
            if conn is not None:
                conn.rollback()
            raise InspectionError("storage_unavailable", 503) from None
        finally:
            if conn is not None:
                conn.close()

    @staticmethod
    def _attempt_matches(attempt, identity):
        return attempt is not None and (
            attempt["attempt_id"] == identity["runtime_attempt_id"]
            and attempt["attempt_revision"] == identity["registry_revision"]
            and attempt["attempt_run_date"].isoformat() == identity["run_date"]
            and attempt["attempt_status"] == "applied"
            and attempt["attempt_outcome"] == "published"
            and attempt["attempt_publication_id"] == identity["publication_id"]
            and attempt["intent_registry_id"] == identity["registry_id"]
            and attempt["intent_revision"] == identity["registry_revision"]
            and attempt["intent_engine_id"] == identity["engine_strategy_id"]
            and attempt["intent_portfolio_id"] == identity["portfolio_id"]
            and attempt["intent_action"] == "run"
        )

    @staticmethod
    def _config_attempt_matches(attempt, publication):
        if attempt is None:return False
        identity=publication['identity'];selection=publication['configuration_selection']
        frozen=attempt['selection']
        if type(frozen) is not dict or set(frozen)!={'scope','schema','source','version_id','base_sha256','engine_build','effective_sha256'}:return False
        return (attempt['attempt_id']==identity['config_attempt_id']
            and attempt['portfolio_id']==identity['portfolio_id']
            and attempt['engine_strategy_id']==identity['engine_strategy_id']
            and attempt['run_date'].isoformat()==identity['run_date']
            and attempt['engine_build']==identity['producer_version']
            and attempt['classification_version']==2
            and attempt['state']=='published' and attempt['lifecycle']=='published'
            and attempt['sealed_publication_id']==identity['publication_id']
            and frozen.get('scope')=={'registry_id':identity['registry_id'],
                'registry_revision':identity['registry_revision'],'investor_book_id':None,
                'portfolio_id':identity['portfolio_id'],'engine_strategy_id':identity['engine_strategy_id']}
            and type(frozen) is dict and frozen.get('schema')=='live-config-selection/v1'
            and all(frozen.get(key)==value for key,value in selection.items())
            and frozen.get('engine_build')==identity['producer_version']
            and attempt['config_snapshot']==publication['supplied']['effective_snapshot'])
