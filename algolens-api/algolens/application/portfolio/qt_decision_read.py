"""Read-only QT presentation and independently proven current report readiness."""
from copy import deepcopy
from algolens.domain.portfolio.qt_workflow_errors import QtWorkflowError
from datetime import date, datetime, timezone
from uuid import UUID
from algolens.application.portfolio.qt_workflow import QtWorkflowService
from algolens.application.portfolio.qt_ports import (QtDecisionReadRepositoryPort, QtEvidencePort, QtInputLoaderPort, QtAuthorizationPort, QtDecisionReadQueriesPort)
from algolens.domain.portfolio.qt_workflow_models import (SCHEMA_VERSION, QtKey, QtSelectionRow,
    QtProposalResponse, QtDecisionResponse)
from algolens.domain.portfolio.qt_instrument_type_resolution import registry_asset_class





def _stamp(value):
    return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z') if isinstance(value, datetime) else value






class QtBookDecisionView:
    def __init__(self, book_id, source_day, decision=None, preview=None):
        if (decision is None) != (preview is None): raise QtWorkflowError('preview_mismatch')
        self._payload = {'schema_version': SCHEMA_VERSION, 'book_id': book_id,
            'source_day': str(source_day), 'decision': decision, 'preview': preview}

    def to_wire(self):
        return deepcopy(self._payload)




class QtDecisionReadService:
    def __init__(self, repository: QtDecisionReadRepositoryPort, *, evidence: QtEvidencePort,
                 input_loader: QtInputLoaderPort, authorization: QtAuthorizationPort,
                 queries: QtDecisionReadQueriesPort, workflow: QtWorkflowService, evaluator_bundle_directory=None):
        self.repository, self.evidence, self.input_loader = repository, evidence, input_loader
        self.authorization, self.queries, self.workflow = authorization, queries, workflow
        self.evaluator_bundle_directory = evaluator_bundle_directory

    def _enabled_prerequisites(self, tx):
        return self.queries.enabled_prerequisites(tx, self.evaluator_bundle_directory)

    def _report_blocked_reasons(self, evidence):
        try:
            self.evidence.prove_report(evidence)
            return ()
        except (ValueError, TypeError, KeyError, ArithmeticError, QtWorkflowError, StopIteration):
            return ('report_snapshot_stale',)


    def ensure_legacy_disabled(self, book_id, actor_id):
        with self.repository.transaction(book_id, actor_id) as tx:
            accounts = tx.lock_authorities([actor_id])
            QtWorkflowService._account_eligible(accounts, actor_id)
            ids = tx.registry_ids_for_book()
            if not ids: raise QtWorkflowError('authorization_changed')
            registries = tx.lock_registries(ids)
            if not any(row['portfolio_id'] == book_id and row['is_active'] for row in registries):
                raise QtWorkflowError('authorization_changed')
            tx.lock_books([book_id])
            day = tx.utc_source_day()
            tx.lock_mutable(source_day=day)
            self.queries.require_legacy_disabled(tx)

    @staticmethod
    def _access(tx, accounts, facts, registry_ids, actor, *, require_desk_grant=True):
        QtWorkflowService._account_eligible(accounts, actor)
        authority = tx.approval_authority(actor)
        if require_desk_grant and not any(row.get('capability') in {'qt_submit', 'qt_approve'} and row.get('active') is True
                   and row.get('user_id') == actor for row in authority['grants']):
            raise QtWorkflowError('authorization_changed')
        if tuple(sorted(row['id'] for row in facts['registry'])) != registry_ids:
            raise QtWorkflowError('authorization_changed')
        members = {(row['strategy_id'], row['portfolio_id']) for row in facts['memberships']}
        if not any(row['is_active'] and row['lifecycle'] == 'live'
                   and (row['portfolio_id'] == tx.book_id or (row['id'], tx.book_id) in members)
                   and QtWorkflowService._owner_membership(row, tx.book_id, members) for row in facts['registry']):
            raise QtWorkflowError('authorization_changed')

    def _read_context(self, tx, actor):
        accounts = tx.lock_authorities([actor])
        ids = tx.registry_ids_for_book()
        registries = tx.lock_registries(ids)
        tx.lock_books([tx.book_id])
        day = tx.utc_source_day()
        tx.lock_mutable(source_day=day)
        facts = tx.read_current_facts()
        if facts['source_day'] != day.isoformat(): raise QtWorkflowError('draft_stale')
        self._access(tx, accounts, facts, ids, actor)
        source = tx.read_source_evidence()
        if source['source_day'] != day: raise QtWorkflowError('draft_stale')
        provenance = self.evidence.reconcile_source(tx.book_id, day, source['publications'], source['source_rows'],
            source['audits'], observed_saved_rows=source['saved_rows'], observed_system_rows=source['system_rows'],
            observed_saved_accounting=source['saved_accounting'], processed_publications=source['processed_publications'])
        return day, facts, source, provenance, registries

    def get_proposal(self, book_id, actor_id):
        with self.repository.transaction(book_id, actor_id) as tx:
            day, facts, source, provenance, registries = self._read_context(tx, actor_id)
            cap = facts['capability']
            available = cap['status'] == 'present' and type(cap.get('version')) is int and cap['version'] > 0
            if available and cap['enabled']: available = self._enabled_prerequisites(tx)
            ready = available and cap['enabled'] and provenance.status == 'ready'
            authority = tx.approval_authority(actor_id)
            submit = ready and any(row['capability'] == 'qt_submit' and row['active'] for row in authority['grants'])
            approve = False
            if ready:
                try: self.authorization.resolve(actor_id, tx); approve = True
                except QtWorkflowError: pass
            seeds = []
            saved = []
            verified = provenance.status == 'ready'
            traces = {trace.source_key: trace for trace in provenance.verified_qt_edits} if verified else {}
            seedkeys = [QtKey(row.key.portfolio_id, row.key.strategy_id, row.key.strategy_name,
                               row.key.date, row.key.symbol, 'qt_proposal') for row in provenance.seed_rows] if verified else []
            keys = [*seedkeys, *(QtKey.from_wire(row['key']) for row in source['saved_rows'])]
            # Catalog first; only when it is silent, fall back PER KEY to
            # that key's own registered strategy's declared asset class --
            # never unioned across the book's other strategies, never
            # invented from a name, never a price table.
            types = tx.resolve_instrument_types(keys, registry_asset_class(registries))
            for key, row in zip(seedkeys, provenance.seed_rows):
                seeds.append(QtSelectionRow(key, row.quantity_exact, 'preserved_source',
                    row.average_price_exact, types[key], True, 'verified_model_seed').to_wire())
            for row in source['saved_rows']:
                key = QtKey.from_wire(row['key'])
                trace = traces.get(key)
                origin = ('verified_qt_decision' if trace.origin == 'verified_qt_decision' else 'reconciled_legacy_draft') if trace else 'immutable'
                saved.append(QtSelectionRow(key, row['quantity_exact'], 'preserved_source',
                    row['average_price_exact'], types[key], trace is not None, origin).to_wire())
            if ready: QtWorkflowService._preview_access(facts, {'selection_rows': seeds})
            state = 'ready' if ready else ('workflow_unavailable' if not available or not cap['enabled'] else 'provenance_unresolved')
            payload = {'schema_version': SCHEMA_VERSION, 'book_id': book_id,
                'source_day': day.isoformat(), 'capability': {'required': cap.get('enabled') is True,
                    'available': available, 'version': cap.get('version') if available else None},
                'workflow_state': state, 'read_only_reason': None if ready else state,
                'action_grants': {'can_save_draft': submit, 'can_confirm': submit, 'can_approve': approve},
                'source_digest': provenance.observed_source_digest, 'provenance_digest': provenance.legacy_audit_chain_digest,
                'seed_publication_id': str(provenance.model_publication_id) if verified else None,
                'seed_rows': seeds, 'saved_qt_rows': saved}
            choice = getattr(provenance, 'empty_owner_choice', None)
            if ready and choice is not None and not seeds and not saved:
                payload.update(schema_version='qt-workflow/v2', empty_owner=dict(choice))
            return QtProposalResponse.from_wire(payload)

    def get_draft(self, book_id, actor_id):
        with self.repository.transaction(book_id, actor_id) as tx:
            day, facts, source, provenance, registries = self._read_context(tx, actor_id)
            head = tx.get_draft_head(day)
            if provenance.status != 'ready' or not facts['capability'].get('enabled'):
                return QtWorkflowService._response(book_id, day, provenance, (), head=head, state='provenance_unresolved')
            # GET /draft is routed here (algolens/adapters/http/qt_workflow.py),
            # not through QtWorkflowService.get_draft -- same registry fallback
            # as get_proposal, or this route alone stays catalog-only.
            base, immutable = QtWorkflowService._base_rows(tx, source, provenance, registry_asset_class(registries))
            QtWorkflowService._preview_access(facts, {'selection_rows': [row.to_wire() for row in base.values()]})
            if head is None: return QtWorkflowService._response(book_id, day, provenance, (*base.values(), *immutable))
            rows = QtWorkflowService._stored_rows(head)
            QtWorkflowService._preview_access(facts, {'selection_rows': [row.to_wire() for row in rows]})
            state = 'saved' if (head['source_digest'] == provenance.observed_source_digest and
                head['provenance_digest'] == provenance.legacy_audit_chain_digest and
                QtWorkflowService._immutable_matches(rows, immutable)) else 'stale'
            if state == 'stale' and QtWorkflowService._receipt_successor(head, provenance, day):
                rows = (*base.values(), *immutable)
            return QtWorkflowService._response(book_id, day, provenance, rows, head=head, state=state)

    def get_decision(self, decision_id, actor_id):
        route = self.repository.decision_routing(decision_id)
        return self._read_decision(route, actor_id)

    def get_book_decision(self, book_id, actor_id, source_day=None):
        explicit = source_day is not None
        if explicit:
            try:
                parsed = date.fromisoformat(source_day)
                if parsed.isoformat() != source_day: raise ValueError()
                source_day = parsed
            except (ValueError, TypeError): raise QtWorkflowError('invalid_qt_payload') from None
        requested_day, route = self.repository.latest_routing(book_id, source_day)
        if route is not None:
            return self._read_decision(route, actor_id, latest_scope=(book_id, requested_day, explicit))
        with self.repository.transaction(book_id, actor_id) as tx:
            day, _, _, _, _ = self._read_context(tx, actor_id)
            if not explicit and requested_day != day: raise QtWorkflowError('authorization_changed', retryable=True)
            if self.queries.latest_decision_id(tx, book_id, requested_day) is not None: raise QtWorkflowError('authorization_changed', retryable=True)
            return QtBookDecisionView(book_id, requested_day)

    def with_processed_snapshot(self, decision_id, actor_id, release_action):
        """Authorize and freeze a release inside the current processing proof locks."""
        route = self.repository.decision_routing(decision_id)
        return self._read_decision(route, actor_id, release_action=release_action)

    def _read_decision(self, route, actor_id, latest_scope=None, release_action=None):
        d, approvals = route['decision'], route['approvals']
        decision_id = str(d['decision_id'])
        discovered = QtWorkflowService._approval_snapshot(approvals)
        book, submitter = d['book_id'], d['created_by']
        with self.repository.transaction(book, actor_id) as tx:
            accounts = tx.lock_authorities({actor_id, submitter, *(row['user_id'] for row in approvals)})
            if release_action is not None:
                release_action.authorize(tx)
            ids = tx.registry_ids_for_book()
            registries = tx.lock_registries(ids)
            tx.lock_books([book])
            day = tx.utc_source_day()
            tx.lock_mutable(source_day=day, preview_ids=[d['preview_id']], decision_ids=[decision_id],
                request_ids=[route['request']['request_id']] if route['request'] else [],
                approval_ids=[row['approval_id'] for row in approvals])
            context = self.queries.decision_context(tx, decision_id, book)
            current = context['decision']
            if any(str(current[name]) != str(d[name]) for name in ['book_id', 'source_day', 'preview_id', 'created_by']) or QtWorkflowService._approval_snapshot(context['approvals']) != discovered:
                raise QtWorkflowError('authorization_changed', retryable=True)
            if latest_scope is not None:
                requested_book, requested_day, explicit = latest_scope
                if book != requested_book or str(current['source_day']) != str(requested_day) or (not explicit and day != requested_day):
                    raise QtWorkflowError('authorization_changed', retryable=True)
                latest = self.queries.latest_decision_id(tx, book, requested_day)
                if latest is None or latest != decision_id:
                    raise QtWorkflowError('authorization_changed', retryable=True)
            if release_action is not None:
                QtWorkflowService._account_eligible(accounts, actor_id)
                replay = release_action.replay(tx, current)
                if replay is not None:
                    return replay
            facts = tx.read_current_facts(actor_id=submitter)
            self._access(tx, accounts, facts, ids, actor_id, require_desk_grant=release_action is None)
            preview = tx.get_preview(current['preview_id'])
            if preview is None: raise QtWorkflowError('not_found')
            from algolens.domain.portfolio.qt_workflow_models import QtPreviewResponse
            public_preview = QtPreviewResponse.from_wire(preview['payload']).to_wire()
            reference = {'schema_version': 'qt-desk-decision/v1', 'decision_id': decision_id,
                'preview_id': str(current['preview_id']), 'book_id': book, 'source_day': str(current['source_day']),
                'preview_payload_digest': preview['payload_digest'], 'selected_book_digest': current['selected_book_digest'],
                'read_set_digest': current['read_set_digest']}
            if (current['payload'] != reference or any(str(preview[name]) != str(current[name]) for name in
                    ['preview_id','book_id','source_day','draft_id','draft_revision','provenance_digest','read_set_digest','selected_book_digest'])
                    or any(public_preview[name] != preview[name] for name in
                    ['payload_digest','read_set_digest','selected_book_digest'])):
                raise QtWorkflowError('preview_mismatch')
            QtWorkflowService._preview_access(facts, preview['payload'])
            receipt = tx.get_receipt(decision_id)
            blocked = ['desk_receipt_pending']
            can_approve = False
            approvals = context['approvals']
            counted_current = True
            for approval in approvals:
                try:
                    person = self.authorization.resolve(approval['user_id'], tx)
                    if any(approval[name] != getattr(person, name) for name in ['person_id','user_id','mapping_version','grant_version']): counted_current = False
                except QtWorkflowError: counted_current = False
            if current['status'] == 'pending_override':
                try:
                    person = self.authorization.resolve(actor_id, tx)
                    QtWorkflowService._authorized(facts, submitter, ids)
                    QtWorkflowService._account_eligible(accounts, submitter)
                    # Same registry fallback as get_proposal/get_draft: for an
                    # equity book the catalog alone raises
                    # draft_identity_unresolved, which the except below
                    # swallows into can_approve staying False, so the
                    # approve button never appears (F2).
                    _, _, _, policy = self.workflow._validate_preview_evidence(
                        tx, preview, book, day, facts, registry_asset_class(registries))
                    can_approve = (self._enabled_prerequisites(tx) and preview['state'] == 'pending_override' and
                        context['request']['required_approvals'] == 2 and counted_current and
                        context['request']['eligibility_version'] == policy['version']) and not any(
                        row['user_id'] == actor_id or row['person_id'] == person.person_id for row in approvals)
                except QtWorkflowError: pass
            elif receipt is not None:
                blocked = ['desk_receipt_failed'] if receipt['status'] == 'failed' else ['desk_receipt_pending']
                if receipt['status'] == 'processed':
                    try:
                        inputs = self.input_loader.load(tx, source_day=day,
                            model_publication_id=current['model_publication_id'], checked_at=facts['captured_at'])
                        facts.update(inputs.read_set_overrides)
                        blocked = list(self._report_blocked_reasons(self.queries.publication_evidence(tx, context, preview, receipt, facts)))
                        if not counted_current: blocked = ['authorization_changed']
                    except (QtWorkflowError, ValueError, KeyError, TypeError): blocked = ['report_snapshot_stale']
            public = [{'person_id': row['person_id'], 'display_label': row['person_id'].replace('_',' '),
                       'user_id': str(row['user_id']), 'approved_at': _stamp(row['approved_at'])} for row in approvals]
            receipt_wire = None if receipt is None else {'status': receipt['status'],
                'published_book_digest': receipt['published_book_digest'], 'report_eligibility': {
                    'status': receipt['report_eligibility_status'], 'reason_codes': receipt['report_reason_codes'],
                    'row_manifest_digest': receipt['row_manifest_digest']}}
            response = QtDecisionResponse.from_wire({'schema_version': SCHEMA_VERSION, 'book_id': book,
                'preview_id': str(current['preview_id']), 'decision_id': str(current['decision_id']),
                'request_id': str(context['request']['request_id']) if context['request'] else None,
                'status': current['status'], 'selected_book_digest': current['selected_book_digest'],
                'read_set_digest': current['read_set_digest'], 'approvals': public, 'approvals_count': len(public),
                'required_approvals': 2, 'can_approve': can_approve, 'receipt': receipt_wire,
                'report_ready': not blocked, 'report_blocked_reasons': blocked})
            if release_action is not None:
                if blocked:
                    raise QtWorkflowError('decision_not_publishable')
                return release_action.save(tx, context, receipt)
            return (QtBookDecisionView(book, latest_scope[1], response.to_wire(), public_preview)
                    if latest_scope is not None else response)
