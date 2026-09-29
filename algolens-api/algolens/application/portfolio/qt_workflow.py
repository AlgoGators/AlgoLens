"""Versioned QT draft reads and saves. No position or result publication occurs here."""

from collections.abc import Mapping
from copy import deepcopy
from hashlib import sha256
import json
from datetime import datetime, timezone
from dataclasses import asdict
from uuid import UUID, uuid4

from algolens.domain.portfolio.qt_canonical import qt_digest_v1, qt_book_digest_v1
from algolens.domain.portfolio.qt_workflow_errors import QtWorkflowError
from algolens.domain.portfolio.qt_workflow_models import (
    SCHEMA_VERSION, QtDraftResponse, QtDraftSaveRequest, QtKey,
    QtSelectionRow, QtCreatePreviewRequest, QtPreviewResponse, parse_qt_selection,
    QtConfirmRequest, QtDecisionResponse, QtApproveRequest,
)


from algolens.application.portfolio.qt_ports import (QtWorkflowRepositoryPort, QtEvidencePort,
    QtInputLoaderPort, QtEvaluatorPort, QtAuthorizationPort)
from algolens.domain.portfolio.qt_instrument_type_resolution import registry_asset_class


class QtWorkflowService:
    def __init__(self, repository: QtWorkflowRepositoryPort, *, evidence: QtEvidencePort,
                 input_loader: QtInputLoaderPort, evaluator: QtEvaluatorPort, authorization: QtAuthorizationPort):
        self.repository, self.evidence, self.input_loader = repository, evidence, input_loader
        self.evaluator, self.authorization = evaluator, authorization

    @property
    def evaluator_bundle_directory(self):
        return self.evaluator.bundle_directory

    @property
    def evaluator_executable(self):
        return self.evaluator.executable

    @staticmethod
    def _authorized(facts: Mapping[str, object], actor_id: int, locked_ids: tuple[str, ...]) -> None:
        if facts["capability"]["status"] != "present" or not facts["capability"]["enabled"]:
            raise QtWorkflowError("workflow_unavailable")
        if not any(grant["user_id"] == str(actor_id) and grant["capability"] == "qt_submit"
                   and grant["active"] for grant in facts["grants"]):
            raise QtWorkflowError("authorization_changed")
        if tuple(sorted(item["id"] for item in facts["registry"])) != locked_ids:
            raise QtWorkflowError("authorization_changed")

    def _locked_context(self, tx, book_id: str, actor_id: int):
        accounts = tx.lock_authorities([actor_id])
        self._account_eligible(accounts, actor_id)
        registry_ids = tx.registry_ids_for_book()
        registries = tx.lock_registries(registry_ids)
        tx.lock_books([book_id])
        day = tx.utc_source_day()
        tx.lock_mutable(source_day=day)
        facts = tx.read_current_facts()
        if facts["source_day"] != day.isoformat():
            raise QtWorkflowError("draft_stale", "QT source day changed during this request")
        self._authorized(facts, actor_id, registry_ids)
        # Catalog first; only when it is silent, fall back PER KEY to that
        # key's own registered strategy's declared asset class -- never
        # unioned across the book's other strategies, never invented from a
        # name, never a price table.
        return day, facts, registry_asset_class(registries)

    @staticmethod
    def _account_eligible(accounts, actor_id):
        if not accounts or not any(row.get("id") == actor_id and row.get("role") in {"admin", "general_member"}
                                   for row in accounts):
            raise QtWorkflowError("authorization_changed")

    @staticmethod
    def _book_owners(facts, engine, book):
        members = {(row["strategy_id"], row["portfolio_id"]) for row in facts["memberships"]}
        return [row for row in facts["registry"] if row["strategy_type"] == engine
            and (row["portfolio_id"] == book or (row["id"], book) in members)]

    @staticmethod
    def _owner_membership(owner, book, members):
        return (owner["id"], book) in members

    @staticmethod
    def _preview_access(facts, payload):
        members = {(row["strategy_id"], row["portfolio_id"]) for row in facts["memberships"]}
        for row in payload["selection_rows"]:
            if not row["editable"]: continue
            key = QtKey.from_wire(row["key"])
            owners = [item for item in QtWorkflowService._book_owners(facts, key.strategy_id, key.portfolio_id)
                if item["is_active"] and item["lifecycle"] == "live"]
            if len(owners) != 1 or not QtWorkflowService._owner_membership(owners[0], key.portfolio_id, members):
                raise QtWorkflowError("authorization_changed")

    def _source_context(self, tx, book_id: str, day, facts):
        source = tx.read_source_evidence()
        if source["source_day"] != day:
            raise QtWorkflowError("draft_stale", "QT source day changed during this request")
        provenance = self.evidence.reconcile_source(
            book_id, day, source["publications"], source["source_rows"], source["audits"],
            observed_saved_rows=source["saved_rows"],
            observed_system_rows=source["system_rows"],
            observed_saved_accounting=source.get("saved_accounting", ()),
            processed_publications=source.get("processed_publications", ()),
        )
        if provenance.status != "ready" or provenance.observed_source_digest is None or provenance.legacy_audit_chain_digest is None:
            raise QtWorkflowError("provenance_unresolved")
        if (facts["provenance"]["source_digest"] != provenance.observed_source_digest
                or facts["provenance"]["chain_digest"] != provenance.legacy_audit_chain_digest):
            raise QtWorkflowError("draft_stale", "QT source changed during this request")
        return source, provenance

    def _context(self, tx, book_id: str, actor_id: int):
        day, facts, registry_kind = self._locked_context(tx, book_id, actor_id)
        source, provenance = self._source_context(tx, book_id, day, facts)
        return day, facts, source, provenance, registry_kind

    @staticmethod
    def _base_rows(tx, source, provenance, registry_kind=None):
        overlay = {row.key: row for row in provenance.draft_overlay}
        def proposal_key(key):
            return QtKey(key.portfolio_id, key.strategy_id, key.strategy_name,
                         key.date, key.symbol, "qt_proposal")

        proposal_keys = {proposal_key(row.key) for row in provenance.seed_rows}
        proposal_keys.update(overlay)
        receipt_keys = {trace.target_key for trace in provenance.verified_qt_edits if trace.origin == "verified_qt_decision"}
        saved_keys = [QtKey.from_wire(row["key"]) for row in source["saved_rows"]]
        independent_saved = [key for key in saved_keys if QtKey(
            key.portfolio_id, key.strategy_id, key.strategy_name, key.date,
            key.symbol, "qt_proposal") not in proposal_keys]
        types = tx.resolve_instrument_types((*proposal_keys, *independent_saved), registry_kind)
        editable = {}
        positions = {proposal_key(row.key): row for row in provenance.seed_rows}
        positions.update(overlay)
        for target, chosen in sorted(positions.items()):
            editable[target] = QtSelectionRow(
                target, chosen.quantity_exact, "preserved_source",
                chosen.average_price_exact, types[target], True,
                "verified_qt_decision" if target in receipt_keys else "reconciled_legacy_draft" if target in overlay else "verified_model_seed",
            )
        immutable = []
        for row in source["saved_rows"]:
            key = QtKey.from_wire(row["key"])
            if key in independent_saved:
                immutable.append(QtSelectionRow(
                    key, row["quantity_exact"], "preserved_source",
                    row["average_price_exact"], types[key], False, "immutable",
                ))
        return editable, tuple(sorted(immutable, key=lambda item: item.key))

    @staticmethod
    def _response(book_id, day, provenance, rows, *, head=None, state=None):
        payload = {
            "schema_version": SCHEMA_VERSION, "book_id": book_id,
            "source_day": day.isoformat(), "state": state or ("saved" if head else "absent"),
            "draft_id": str(head["draft_id"]) if head else None,
            "draft_revision": head["revision"] if head else 0,
            "draft_digest": head["draft_digest"] if head else None,
            "source_digest": provenance.observed_source_digest,
            "provenance_digest": provenance.legacy_audit_chain_digest,
            "selection_rows": [row.to_wire() for row in rows],
        }
        choice = getattr(provenance, "empty_owner_choice", None)
        if choice is not None and provenance.status == "ready" and payload["state"] == "stale" and not rows and QtWorkflowService._receipt_successor(head, provenance, day):
            link = provenance.receipt_links[-1]
            payload.update(schema_version="qt-workflow/v2", state="consumed", empty_owner=dict(choice),
                successor={name: link[name] for name in ("decision_id", "attempt_id", "preview_id", "publication_digest")})
        if choice is not None and provenance.status == "ready" and payload["state"] in {"absent", "saved"} and not rows:
            payload.update(schema_version="qt-workflow/v2", empty_owner=dict(choice))
        return QtDraftResponse.from_wire(payload)

    @staticmethod
    def _stored_rows(head):
        payload = head["selection_payload"]
        if (not isinstance(payload, Mapping) or set(payload) != {"selection_rows"}
                or qt_digest_v1(payload) != head["draft_digest"]):
            raise QtWorkflowError("draft_identity_unresolved", "Stored QT draft digest is invalid")
        rows = tuple(QtSelectionRow.from_wire(item) for item in payload["selection_rows"])
        if len({row.key for row in rows}) != len(rows):
            raise QtWorkflowError("draft_identity_unresolved", "Stored QT draft has duplicate keys")
        return rows

    @staticmethod
    def _immutable_matches(rows, current):
        stored = tuple(sorted((row for row in rows if not row.editable), key=lambda row: row.key))
        return stored == current

    @staticmethod
    def _receipt_successor(head, provenance, day):
        """Allow only an explicit next choice rooted in its exact consumed receipt."""
        if head is None or not provenance.receipt_links or not provenance.receipt_decisions:
            return False
        try:
            decision = provenance.receipt_decisions[-1]
            choice = getattr(provenance, "empty_owner_choice", None)
            if choice is not None:
                link = provenance.receipt_links[-1]
                if (decision.get("empty_owner_choice") != dict(choice) or decision.get("status") != "confirmed_decision"
                        or decision.get("book_id") != head.get("book_id")
                        or str(decision["decision_id"]) != link["decision_id"]
                        or str(decision["preview_id"]) != link["preview_id"]): return False
            return (head["provenance_digest"] != provenance.legacy_audit_chain_digest
                and str(decision["source_day"]) == day.isoformat()
                and str(decision["draft_id"]) == str(head["draft_id"])
                and decision["draft_revision"] == head["revision"]
                and decision["draft_digest"] == decision["selection_digest"] == head["draft_digest"]
                and qt_digest_v1(head["selection_payload"]) == head["draft_digest"]
                and decision["provenance_digest"] == head["provenance_digest"]
                and decision["source_digest"] == head["source_digest"] == provenance.observed_source_digest
                and str(decision["model_publication_id"]) == str(head["model_publication_id"]) == provenance.model_publication_id
                and head["model_publication_version"] == provenance.model_publication_version
                and head["seed_digest"] == provenance.seed_digest)
        except (KeyError, TypeError, ValueError, QtWorkflowError):
            return False

    def get_draft(self, book_id: str, actor_id: int) -> QtDraftResponse:
        with self.repository.transaction(book_id, actor_id) as tx:
            day, _, source, provenance, registry_kind = self._context(tx, book_id, actor_id)
            base, immutable = self._base_rows(tx, source, provenance, registry_kind)
            head = tx.get_draft_head(day)
            if head is None:
                return self._response(book_id, day, provenance, (*base.values(), *immutable))
            rows = self._stored_rows(head)
            state = "saved" if (head["source_digest"] == provenance.observed_source_digest
                                and head["provenance_digest"] == provenance.legacy_audit_chain_digest
                                and self._immutable_matches(rows, immutable)) else "stale"
            if state == "stale" and self._receipt_successor(head, provenance, day):
                rows = (*base.values(), *immutable)
            return self._response(book_id, day, provenance, rows, head=head, state=state)

    def save_draft(self, book_id: str, actor_id: int,
                   request: QtDraftSaveRequest | Mapping[str, object]) -> QtDraftResponse:
        if isinstance(request, Mapping):
            request = QtDraftSaveRequest.from_wire(request)
        if not isinstance(request, QtDraftSaveRequest):
            raise QtWorkflowError("invalid_qt_payload")
        request_wire = request.to_wire()
        request_digest = qt_digest_v1(request_wire)
        with self.repository.transaction(book_id, actor_id) as tx:
            day, facts, registry_kind = self._locked_context(tx, book_id, actor_id)
            replay = tx.get_idempotent("save_draft", day.isoformat(), request.idempotency_key, request_digest)
            if replay is not None:
                if replay.get("book_id") != book_id or replay.get("source_day") != day.isoformat():
                    raise QtWorkflowError("draft_identity_unresolved", "Stored QT retry scope is invalid")
                return QtDraftResponse.from_wire(replay)
            source, provenance = self._source_context(tx, book_id, day, facts)
            if (request.expected_source_digest != provenance.observed_source_digest
                    or request.expected_provenance_digest != provenance.legacy_audit_chain_digest):
                raise QtWorkflowError("draft_stale")
            head = tx.get_draft_head(day)
            current_revision = head["revision"] if head else 0
            if current_revision != request.expected_draft_revision:
                raise QtWorkflowError("draft_stale")
            successor = self._receipt_successor(head, provenance, day)
            if head is not None and (head["source_digest"] != provenance.observed_source_digest
                                     or head["provenance_digest"] != provenance.legacy_audit_chain_digest) and not successor:
                raise QtWorkflowError("draft_stale", "A prior QT draft belongs to different source evidence")
            base, immutable = self._base_rows(tx, source, provenance, registry_kind)
            saved = self._stored_rows(head) if head and not successor else ()
            if head is not None and not successor and not self._immutable_matches(saved, immutable):
                raise QtWorkflowError("draft_stale", "An independent saved QT component changed")
            editable = {**base, **{row.key: row for row in saved if row.editable}}
            submitted = [QtKey.from_wire(row["key"]) for row in request_wire["selection_rows"]]
            if len(set(submitted)) != len(submitted):
                raise QtWorkflowError("invalid_qt_key", "Duplicate QT component")
            memberships = {(item["strategy_id"], item["portfolio_id"]) for item in facts["memberships"]}
            known_names = {}
            for key in base:
                known_names.setdefault(key.strategy_id, set()).add(key.strategy_name)
            for key in submitted:
                if key.portfolio_id != book_id or key.date != day.isoformat() or key.portfolio_type != "qt_proposal":
                    raise QtWorkflowError("invalid_qt_key", "QT component is outside current source scope")
                owners = [item for item in self._book_owners(facts, key.strategy_id, book_id)
                    if item["is_active"] and item["lifecycle"] == "live"]
                if len(owners) != 1 or not self._owner_membership(owners[0], book_id, memberships):
                    raise QtWorkflowError("draft_identity_unresolved")
                if key not in editable and known_names.get(key.strategy_id) != {key.strategy_name}:
                    raise QtWorkflowError("draft_identity_unresolved", "New QT component ownership is ambiguous")
            if not set(base).issubset(submitted):
                raise QtWorkflowError("invalid_qt_key", "Complete QT editable selection is required")
            kinds = tx.resolve_instrument_types(submitted, registry_kind)
            rows = parse_qt_selection(request_wire["selection_rows"], frozenset(submitted), kinds,
                                      source_rows=editable, immutable_rows=immutable)
            draft_id = str(uuid4())
            revision = current_revision + 1
            payload = {"selection_rows": [row.to_wire() for row in rows]}
            digest = qt_digest_v1(payload)
            tx.insert_draft_revision({
                "draft_id": draft_id, "book_id": book_id, "source_day": day,
                "revision": revision, "model_publication_id": provenance.model_publication_id,
                "model_publication_version": provenance.model_publication_version,
                "seed_digest": provenance.seed_digest,
                "source_digest": provenance.observed_source_digest,
                "provenance_digest": provenance.legacy_audit_chain_digest,
                "draft_digest": digest, "selection_payload": payload,
                "created_by": actor_id, "updated_by": actor_id,
            })
            tx.advance_draft_head(day, current_revision, draft_id, revision)
            response = self._response(book_id, day, provenance, rows,
                                      head={"draft_id": draft_id, "revision": revision, "draft_digest": digest})
            tx.insert_idempotent("save_draft", day.isoformat(), request.idempotency_key,
                                 request_digest, response.to_wire())
            return response

    @staticmethod
    def _target_digest(rows):
        target = [{"key": {**row.key.to_wire(), "portfolio_type": "qt"}, "quantity_exact": row.quantity_exact}
                  for row in rows]
        return qt_book_digest_v1(target, source_portfolio_type="qt")

    @staticmethod
    def _engine_key(key):
        return QtKey(key.portfolio_id, key.strategy_id, key.strategy_name, key.date, key.symbol, "qt_proposal")

    def _validate_catalog(self, tx, inputs, rows, facts, registry_kind=None):
        expected = {self._engine_key(row.key): row for row in rows}
        if len(expected) != len(rows):
            raise QtWorkflowError("preview_unavailable", "QT engine identity is ambiguous")
        catalog = {QtKey.from_wire(item["key"]): item for item in inputs.instrument_catalog}
        if set(catalog) != set(expected):
            raise QtWorkflowError("preview_unavailable", "Governed catalog does not cover the selected book")
        current_types = tx.resolve_instrument_types(expected, registry_kind)
        for key, row in expected.items():
            item = catalog[key]
            owners = self._book_owners(facts, key.strategy_id, key.portfolio_id)
            if (len(owners) != 1 or (row.editable and (not owners[0]["is_active"] or owners[0]["lifecycle"] != "live"))
                    or item["editable"] is not row.editable or item["instrument_type"] != row.asset_type
                    or current_types[key] != row.asset_type):
                raise QtWorkflowError("preview_unavailable", "Governed catalog differs from current component authority")

    def _engine_request(self, rows, accounting, head, inputs, read_set, operation):
        previous = {self._engine_key(QtKey.from_wire(row["key"])): row for row in accounting}
        slots = []
        quantities = []
        for row in sorted(rows, key=lambda item: item.key):
            key = self._engine_key(row.key)
            actual = previous.get(key)
            prior = None if actual is None else {
                "symbol": key.symbol, "quantity_exact": actual["quantity_exact"],
                "average_price_exact": actual["average_price_exact"],
                "unrealized_pnl_exact": actual["daily_unrealized_pnl_exact"],
                "realized_pnl_exact": actual["daily_realized_pnl_exact"], "last_update": actual["last_update"],
            }
            if not row.editable and prior is None:
                raise QtWorkflowError("preview_unavailable", "Immutable QT accounting is unavailable")
            slots.append({"key": key.to_wire(), "instrument": {"instrument_type": row.asset_type, "symbol": key.symbol},
                          "editable": row.editable, "previous": prior})
            if row.editable:
                quantities.append({"key": key.to_wire(), "quantity_exact": row.quantity_exact})
        context = {"portfolio_id": read_set.payload["book_id"], "date": read_set.source_day,
                   "portfolio_type": "qt_proposal", "revision": f"{head['draft_id']}:{head['revision']}:{head['draft_digest']}",
                   "slots": slots}
        expected = {"expected_portfolio_id": context["portfolio_id"], "expected_date": context["date"],
                    "expected_portfolio_type": context["portfolio_type"], "expected_revision": context["revision"]}
        authority = inputs.engine_inputs
        schema = "qt-eval-empty-owner/v2" if getattr(inputs, "input_schema", "qt-inputs/v1") == "qt-inputs-empty-owner/v2" else "qt-eval/v1"
        req = {"schema": schema, "operation": operation, "evaluator_build": inputs.evaluator_build,
               "context_fingerprint": sha256(self.evidence.input_bytes({"context": context,
                   "read_set_digest": read_set.digest, "source_identity_digest": inputs.source_identity_digest})).hexdigest(),
               "context": context, "proposal": {**expected, "quantities": quantities},
               **{name: authority[name] for name in ("risk_config_source_id", "risk_inputs", "risk_config", "quantity_rules", "component_cost_inputs")}}
        req["risk_inputs"] = {**req["risk_inputs"], **expected}
        if operation == "draft_diagnostic":
            req["optimizer_policy"] = authority["optimizer_policy"]
            if req["optimizer_policy"]["enabled"]:
                req["optimizer_inputs"] = {**authority["optimizer_inputs"], **expected}
                req["optimizer_config"] = authority["optimizer_config"]
        return req

    @staticmethod
    def _project_request(request):
        """Project already validated complete authority to one operation scope."""
        req = deepcopy(request)
        keys = {QtKey.from_wire(slot["key"]) for slot in req["context"]["slots"] if slot["editable"]}
        instruments = {(slot["instrument"]["instrument_type"], slot["instrument"]["symbol"]) for slot in req["context"]["slots"]}
        editable_instruments = {(slot["instrument"]["instrument_type"], slot["instrument"]["symbol"])
                                for slot in req["context"]["slots"] if slot["editable"]}
        def identity(row): return row["instrument"]["instrument_type"], row["instrument"]["symbol"]
        req["component_cost_inputs"] = [row for row in req["component_cost_inputs"] if QtKey.from_wire(row["key"]) in keys]
        req["quantity_rules"] = [row for row in req["quantity_rules"] if identity(row) in instruments]
        for name in ("valuations", "closes"):
            req["risk_inputs"][name] = [row for row in req["risk_inputs"][name] if identity(row) in instruments]
        if "optimizer_inputs" in req:
            for name in ("instruments", "closes"):
                req["optimizer_inputs"][name] = [row for row in req["optimizer_inputs"][name] if identity(row) in editable_instruments]
        return req

    @staticmethod
    def _unavailable_evidence():
        return {
            "optimizer": {"status": "unavailable", "evaluated_book_digest": None, "aggregate_bindings": [],
                          "current_weights": [], "target_weights": [], "solved_weights": [], "trace": [],
                          "cost_penalty": None, "diagnostics": [], "config_source_id": None},
            "selected_risk": {"status": "unavailable", "evaluated_book_digest": None, "passed": None,
                              "breaches": [], "metrics": [], "config_source_id": None, "market_snapshot_id": None, "diagnostics": []},
            "selected_costs": {"status": "unavailable", "evaluated_book_digest": None,
                               "by_component": [], "total_exact": None, "diagnostics": []},
        }

    def create_preview(self, actor_id: int, request: QtCreatePreviewRequest | Mapping[str, object]) -> QtPreviewResponse:
        if isinstance(request, Mapping): request = QtCreatePreviewRequest.from_wire(request)
        if not isinstance(request, QtCreatePreviewRequest): raise QtWorkflowError("invalid_qt_payload")
        request_digest = qt_digest_v1(request.to_wire())
        book_id = request.book_id
        with self.repository.transaction(book_id, actor_id) as tx:
            day, facts, registry_kind = self._locked_context(tx, book_id, actor_id)
            scope = day.isoformat() + ":" + request.draft_id
            replay = tx.get_idempotent("create_preview", scope, request.idempotency_key, request_digest)
            if replay is not None:
                if replay.get("book_id") != book_id or replay.get("source_day") != day.isoformat() or replay.get("draft_id") != request.draft_id:
                    raise QtWorkflowError("preview_mismatch")
                return QtPreviewResponse.from_wire(replay)
            source, provenance = self._source_context(tx, book_id, day, facts)
            head = tx.get_draft_head(day)
            if (head is None or str(head["draft_id"]) != request.draft_id or head["revision"] != request.draft_revision
                    or head["draft_digest"] != request.draft_digest or head["source_digest"] != request.expected_source_digest
                    or head["provenance_digest"] != request.expected_provenance_digest
                    or head["source_digest"] != provenance.observed_source_digest
                    or head["provenance_digest"] != provenance.legacy_audit_chain_digest):
                raise QtWorkflowError("draft_stale")
            rows = self._stored_rows(head)
            base, immutable = self._base_rows(tx, source, provenance, registry_kind)
            if not self._immutable_matches(rows, immutable): raise QtWorkflowError("draft_stale")
            diagnostic_rows = (*base.values(), *immutable)
            selected_digest = self._target_digest(rows)
            optimizer_digest = self._target_digest(diagnostic_rows)
            reasons = []
            inputs = None
            try:
                inputs = self.input_loader.load(tx, source_day=day, model_publication_id=provenance.model_publication_id,
                                                  checked_at=facts["captured_at"])
                overrides = inputs.read_set_overrides
                if set(overrides) != {"risk_limits", "portfolio_inputs", "external_sources", "evaluator"}:
                    raise QtWorkflowError("preview_unavailable")
                facts = {**facts, **overrides}
            except QtWorkflowError as error:
                if error.code != "preview_unavailable": raise
                reasons.append("governed_inputs_unavailable")
            try:
                read_set = self.evidence.capture_read_set(facts)
            except ValueError:
                raise QtWorkflowError("preview_unavailable", "Current QT read-set is invalid") from None
            if inputs is not None and not read_set.available:
                reasons.append("saved_accounting_unavailable")
            evidence = self._unavailable_evidence()
            requires_override = False
            if not reasons:
                if self.evaluator_bundle_directory is None:
                    reasons.append("evaluator_not_configured")
                else:
                    try:
                        self._validate_catalog(tx, inputs, rows, facts, registry_kind)
                        client = self.evaluator.create_client(inputs)
                        selected_request = self._engine_request(rows, facts["saved_accounting"], head, inputs, read_set, "selected_book")
                        client.validate_request(selected_request)
                        authority = inputs.engine_inputs
                        if authority["optimizer_policy"]["enabled"]:
                            client.validate_request(self._engine_request(rows, facts["saved_accounting"], head,
                                                                        inputs, read_set, "draft_diagnostic"))
                        diagnostic_request = self._project_request(self._engine_request(
                            diagnostic_rows, facts["saved_accounting"], head, inputs, read_set, "draft_diagnostic"))
                        diagnostic = client.evaluate(diagnostic_request)
                        selected = client.evaluate(selected_request)
                        if diagnostic.book_digest != optimizer_digest or selected.book_digest != selected_digest:
                            raise QtWorkflowError("preview_mismatch")
                        evidence = selected.evidence
                        evidence["optimizer"] = diagnostic.evidence["optimizer"]
                        reasons.extend(selected.unavailable_reasons)
                        if evidence["optimizer"]["status"] not in {"evaluated", "disabled"}: reasons.append("optimizer_unavailable")
                        requires_override = selected.requires_override and not reasons
                    except (QtWorkflowError, ValueError, TypeError, KeyError):
                        evidence = self._unavailable_evidence()
                        reasons = ["evaluator_evidence_unavailable"]
            latest = tx.read_current_facts()
            self._authorized(latest, actor_id, tuple(sorted(item["id"] for item in facts["registry"])))
            if latest["source_day"] != day.isoformat(): raise QtWorkflowError("preview_stale")
            try:
                latest_inputs = self.input_loader.load(tx, source_day=day, model_publication_id=provenance.model_publication_id,
                                                         checked_at=latest["captured_at"])
                latest = {**latest, **latest_inputs.read_set_overrides}
            except QtWorkflowError as error:
                if error.code != "preview_unavailable": raise
                if inputs is not None: raise QtWorkflowError("preview_stale") from None
            if self.evidence.capture_read_set(latest).digest != read_set.digest: raise QtWorkflowError("preview_stale")
            preview_id = str(uuid4())
            payload = {"schema_version": SCHEMA_VERSION, "book_id": book_id, "source_day": day.isoformat(),
                       "preview_id": preview_id, "optimizer_book_digest": optimizer_digest,
                       "selected_book_digest": selected_digest, "draft_id": request.draft_id,
                       "draft_revision": request.draft_revision, "source_digest": provenance.observed_source_digest,
                       "provenance_digest": provenance.legacy_audit_chain_digest, "read_set_digest": read_set.digest,
                       "availability": "unavailable" if reasons else "ready", "confirmable": not reasons,
                       "requires_override": requires_override, "selection_rows": [row.to_wire() for row in rows],
                       "unavailable_reasons": sorted(set(reasons)), "evaluation": evidence}
            payload["payload_digest"] = qt_digest_v1(payload)
            response = QtPreviewResponse.from_wire(payload)
            tx.insert_preview({"preview_id": preview_id, "book_id": book_id, "source_day": day,
                "draft_id": request.draft_id, "draft_revision": request.draft_revision,
                "draft_digest": request.draft_digest, "source_digest": provenance.observed_source_digest,
                "provenance_digest": provenance.legacy_audit_chain_digest, "read_set_digest": read_set.digest,
                "optimizer_book_digest": optimizer_digest, "selected_book_digest": selected_digest,
                "payload_digest": payload["payload_digest"], "payload": payload,
                "read_set_payload": json.loads(self.evidence.canonical_snapshot("qt-read-set/v1", read_set.payload)),
                "evaluator_build": inputs.evaluator_build if inputs else "unavailable",
                "policy_version": inputs.policy_version if inputs else "unavailable",
                "availability": payload["availability"], "created_by": actor_id, "state": "pending"})
            tx.insert_idempotent("create_preview", scope, request.idempotency_key, request_digest, response.to_wire())
            return response

    def _validate_preview_evidence(self, tx, preview, book_id, day, facts, registry_kind=None):
        try:
            payload = QtPreviewResponse.from_wire(preview["payload"]).to_wire()
            if (qt_digest_v1({key: value for key, value in payload.items() if key != "payload_digest"}) != preview["payload_digest"]
                    or any(str(payload[field]) != str(preview[field]) for field in (
                        "preview_id", "book_id", "source_day", "draft_id", "draft_revision", "source_digest",
                        "provenance_digest", "read_set_digest", "optimizer_book_digest", "selected_book_digest", "payload_digest", "availability"))
                    or not payload["confirmable"] or payload["unavailable_reasons"]):
                raise ValueError()
            stored_digest = sha256(self.evidence.canonical_snapshot("qt-read-set/v1", preview["read_set_payload"])).hexdigest()
            if stored_digest != preview["read_set_digest"]: raise ValueError()
        except (ValueError, KeyError, TypeError, QtWorkflowError):
            raise QtWorkflowError("preview_mismatch") from None
        if str(preview["source_day"]) != day.isoformat() or facts["source_day"] != day.isoformat():
            raise QtWorkflowError("preview_stale")
        try:
            source, provenance = self._source_context(tx, book_id, day, facts)
            head = tx.get_draft_head(day)
            if (head is None or str(head["draft_id"]) != str(preview["draft_id"])
                    or head["revision"] != preview["draft_revision"] or head["draft_digest"] != preview["draft_digest"]
                    or provenance.observed_source_digest != preview["source_digest"]
                    or provenance.legacy_audit_chain_digest != preview["provenance_digest"]):
                raise QtWorkflowError("preview_stale")
            if qt_digest_v1({"selection_rows": payload["selection_rows"]}) != head["draft_digest"]:
                raise QtWorkflowError("preview_mismatch")
            saved_rows = self._stored_rows(head)
            base, immutable = self._base_rows(tx, source, provenance, registry_kind)
            if (self._target_digest(saved_rows) != payload["selected_book_digest"]
                    or self._target_digest((*base.values(), *immutable)) != payload["optimizer_book_digest"]):
                raise QtWorkflowError("preview_mismatch")
            inputs = self.input_loader.load(tx, source_day=day, model_publication_id=provenance.model_publication_id,
                                              checked_at=facts["captured_at"])
            current = self.evidence.capture_read_set({**facts, **inputs.read_set_overrides})
            if (not current.available or current.digest != stored_digest
                    or inputs.evaluator_build != preview["evaluator_build"] or inputs.policy_version != preview["policy_version"]):
                raise QtWorkflowError("preview_stale")
            policy = tx.read_evaluation_policy()
            if (policy is None or policy["enabled"] is not True or type(policy["version"]) is not int or policy["version"] <= 0
                    or policy["policy_version"] != inputs.policy_version
                    or sorted(policy["allowed_override_codes"]) != sorted(inputs.allowed_override_codes)):
                raise QtWorkflowError("preview_stale")
        except (ValueError, TypeError, KeyError): raise QtWorkflowError("preview_stale") from None
        risk = payload["evaluation"]["selected_risk"]
        costs = payload["evaluation"]["selected_costs"]
        optimizer = payload["evaluation"]["optimizer"]
        breaches = {entry["code"] for entry in risk["breaches"]}
        expected_metrics = {"portfolio_var", "jump_risk", "correlation_risk", "gross_leverage", "net_leverage",
            "max_portfolio_risk", "max_jump_risk", "max_leverage_risk", "portfolio_multiplier", "jump_multiplier",
            "correlation_multiplier", "leverage_multiplier", "portfolio_var_gate", "recommended_scale"}
        if (risk["status"] != "evaluated" or costs["status"] != "evaluated"
                or optimizer["status"] not in {"evaluated", "disabled"}
                or risk["evaluated_book_digest"] != payload["selected_book_digest"]
                or costs["evaluated_book_digest"] != payload["selected_book_digest"]
                or {row["code"] for row in risk["metrics"]} != expected_metrics or len(risk["metrics"]) != len(expected_metrics)
                or risk["config_source_id"] != inputs.engine_inputs["risk_config_source_id"]
                or risk["market_snapshot_id"] != inputs.engine_inputs["risk_inputs"]["market_snapshot_id"]
                or any(row["source_id"] != risk["market_snapshot_id"] or row["unit"] != "ratio" for row in risk["metrics"])
                or risk["passed"] is not (not breaches) or breaches - set(inputs.allowed_override_codes)
                or payload["requires_override"] is not bool(breaches)):
            raise QtWorkflowError("preview_unavailable")
        return payload, provenance, inputs, policy

    def confirm_preview(self, preview_id, actor_id: int, request: QtConfirmRequest | Mapping[str, object]) -> QtDecisionResponse:
        if isinstance(request, Mapping): request = QtConfirmRequest.from_wire(request)
        if not isinstance(request, QtConfirmRequest): raise QtWorkflowError("invalid_qt_payload")
        request = QtConfirmRequest.from_wire(request.to_wire())
        preview_id = str(preview_id)
        try:
            if str(UUID(preview_id)) != preview_id: raise ValueError()
        except (ValueError, TypeError): raise QtWorkflowError("invalid_qt_payload") from None
        request_digest = qt_digest_v1(request.to_wire())
        route = self.repository.preview_routing(preview_id)
        if route is None: raise QtWorkflowError("not_found")
        book_id = route["book_id"]
        with self.repository.transaction(book_id, actor_id) as tx:
            self._account_eligible(tx.lock_authorities([actor_id]), actor_id)
            registry_ids = tx.registry_ids_for_book()
            registries = tx.lock_registries(registry_ids)
            registry_kind = registry_asset_class(registries)
            tx.lock_books([book_id])
            day = tx.utc_source_day()
            tx.lock_mutable(source_day=day, preview_ids=[preview_id])
            preview = tx.get_preview(preview_id)
            if (preview is None or preview["book_id"] != book_id or str(preview["preview_id"]) != preview_id
                    or str(preview["source_day"]) != str(route["source_day"])):
                raise QtWorkflowError("not_found")
            facts = tx.read_current_facts()
            self._authorized(facts, actor_id, registry_ids)
            self._preview_access(facts, preview["payload"])
            replay = tx.get_idempotent("confirm_preview", preview_id, request.idempotency_key, request_digest)
            if replay is not None:
                if replay.get("book_id") != book_id or replay.get("preview_id") != preview_id:
                    raise QtWorkflowError("preview_mismatch")
                return QtDecisionResponse.from_wire(replay)
            if preview["state"] != "pending": raise QtWorkflowError("preview_consumed")
            if request.expected_digest != preview["payload_digest"]: raise QtWorkflowError("preview_mismatch")
            if preview["availability"] != "ready": raise QtWorkflowError("preview_unavailable")
            payload, provenance, inputs, policy = self._validate_preview_evidence(tx, preview, book_id, day, facts, registry_kind)
            risk, costs, optimizer = (payload["evaluation"][name] for name in ("selected_risk", "selected_costs", "optimizer"))
            breaches = {entry["code"] for entry in risk["breaches"]}
            warnings = bool(breaches or any(stage["diagnostics"] for stage in (risk, costs, optimizer)))
            if warnings and not request.acknowledge_warnings:
                raise QtWorkflowError("preview_mismatch", "Stored preview warnings require acknowledgement")
            decision_id, request_id = str(uuid4()), str(uuid4()) if breaches else None
            status = "pending_override" if breaches else "confirmed_decision"
            reference = {"schema_version": "qt-desk-decision/v1", "decision_id": decision_id,
                "preview_id": preview_id, "book_id": book_id, "source_day": day.isoformat(),
                "preview_payload_digest": preview["payload_digest"], "selected_book_digest": preview["selected_book_digest"],
                "read_set_digest": preview["read_set_digest"]}
            grant = next(row for row in facts["grants"] if row["user_id"] == str(actor_id) and row["capability"] == "qt_submit" and row["active"])
            tx.consume_preview(preview_id, "pending", status)
            tx.insert_decision({"decision_id": decision_id, "preview_id": preview_id, "book_id": book_id,
                "source_day": day, "status": status, "model_publication_id": provenance.model_publication_id,
                "provenance_digest": preview["provenance_digest"], "draft_id": preview["draft_id"],
                "draft_revision": preview["draft_revision"], "selected_book_digest": preview["selected_book_digest"],
                "read_set_digest": preview["read_set_digest"], "workflow_capability_version": facts["capability"]["version"],
                "submitter_grant_version": grant["version"], "policy_version": inputs.policy_version,
                "payload": reference, "created_by": actor_id})
            if request_id is not None:
                tx.insert_override_request({"request_id": request_id, "decision_id": decision_id,
                    "eligibility_version": policy["version"], "required_approvals": 2})
            response = QtDecisionResponse.from_wire({"schema_version": SCHEMA_VERSION, "book_id": book_id,
                "preview_id": preview_id, "decision_id": decision_id, "request_id": request_id, "status": status,
                "selected_book_digest": preview["selected_book_digest"], "read_set_digest": preview["read_set_digest"],
                "approvals": [], "approvals_count": 0, "required_approvals": 2, "can_approve": False,
                "receipt": None, "report_ready": False, "report_blocked_reasons": ["desk_receipt_pending"]})
            tx.insert_idempotent("confirm_preview", preview_id, request.idempotency_key, request_digest, response.to_wire())
            return response

    @staticmethod
    def _approval_snapshot(approvals):
        return sorted((str(row["approval_id"]), int(row["user_id"]), row["person_id"],
                       row["mapping_version"], row["grant_version"]) for row in approvals)

    def approve_override(self, request_id, actor_id: int, request: QtApproveRequest | Mapping[str, object]) -> QtDecisionResponse:
        if isinstance(request, Mapping): request = QtApproveRequest.from_wire(request)
        if not isinstance(request, QtApproveRequest): raise QtWorkflowError("invalid_qt_payload")
        request = QtApproveRequest.from_wire(request.to_wire())
        request_id = str(request_id)
        try:
            if str(UUID(request_id)) != request_id: raise ValueError()
        except (ValueError, TypeError): raise QtWorkflowError("invalid_qt_payload") from None
        request_digest = qt_digest_v1(request.to_wire())
        route = self.repository.override_routing(request_id)
        if route is None: raise QtWorkflowError("not_found")
        book_id, submitter = route["book_id"], route["created_by"]
        discovered = self._approval_snapshot(route["approvals"])
        users = sorted({actor_id, submitter, *(row[1] for row in discovered)})
        with self.repository.transaction(book_id, actor_id) as tx:
            accounts = tx.lock_authorities(users)
            self._account_eligible(accounts, actor_id)
            registry_ids = tx.registry_ids_for_book()
            registries = tx.lock_registries(registry_ids)
            registry_kind = registry_asset_class(registries)
            tx.lock_books([book_id])
            day = tx.utc_source_day()
            tx.lock_mutable(source_day=day, preview_ids=[route["preview_id"]],
                            decision_ids=[route["decision_id"]], request_ids=[request_id],
                            approval_ids=[row[0] for row in discovered])
            context = tx.get_override_context(request_id)
            if context is None: raise QtWorkflowError("not_found")
            override, decision, approvals = (context[name] for name in ("request", "decision", "approvals"))
            if (str(override["request_id"]) != request_id or str(override["decision_id"]) != str(route["decision_id"])
                    or any(str(decision[name]) != str(route[name]) for name in ("decision_id", "preview_id", "book_id", "source_day", "created_by"))
                    or self._approval_snapshot(approvals) != discovered):
                raise QtWorkflowError("authorization_changed", "Approval routing changed; retry the request", retryable=True)
            preview = tx.get_preview(route["preview_id"])
            if preview is None or preview["book_id"] != book_id: raise QtWorkflowError("not_found")
            person = self.authorization.resolve(actor_id, tx)
            facts = tx.read_current_facts(actor_id=submitter)
            if tuple(sorted(row["id"] for row in facts["registry"])) != registry_ids:
                raise QtWorkflowError("authorization_changed")
            self._preview_access(facts, preview["payload"])
            own_approval = [row for row in approvals if row["user_id"] == actor_id or row["person_id"] == person.person_id]
            if own_approval and any(any(row[name] != value for name, value in asdict(person).items()) for row in own_approval):
                raise QtWorkflowError("authorization_changed")
            replay = tx.get_idempotent("approve_override", request_id, request.idempotency_key, request_digest)
            if replay is not None:
                if replay.get("decision_id") != str(decision["decision_id"]) or replay.get("request_id") != request_id:
                    raise QtWorkflowError("preview_mismatch")
                return QtDecisionResponse.from_wire(replay)
            if decision["status"] != "pending_override" or own_approval:
                raise QtWorkflowError("decision_not_publishable")
            self._account_eligible(accounts, submitter)
            self._authorized(facts, submitter, registry_ids)
            if preview["state"] != "pending_override" or preview["availability"] != "ready":
                raise QtWorkflowError("preview_unavailable")
            payload, provenance, inputs, policy = self._validate_preview_evidence(tx, preview, book_id, day, facts, registry_kind)
            expected_reference = {"schema_version": "qt-desk-decision/v1", "decision_id": str(decision["decision_id"]),
                "preview_id": str(preview["preview_id"]), "book_id": book_id, "source_day": day.isoformat(),
                "preview_payload_digest": preview["payload_digest"], "selected_book_digest": preview["selected_book_digest"],
                "read_set_digest": preview["read_set_digest"]}
            grant = next(row for row in facts["grants"] if row["capability"] == "qt_submit" and row["active"])
            if (override["required_approvals"] != 2 or override["eligibility_version"] != policy["version"]
                    or not payload["requires_override"] or decision["payload"] != expected_reference
                    or any(str(decision[name]) != str(preview[name]) for name in (
                        "preview_id", "book_id", "source_day", "draft_id", "draft_revision", "provenance_digest", "selected_book_digest", "read_set_digest"))
                    or str(decision["model_publication_id"]) != str(provenance.model_publication_id)
                    or decision["policy_version"] != inputs.policy_version
                    or decision["workflow_capability_version"] != facts["capability"]["version"]
                    or decision["submitter_grant_version"] != grant["version"]):
                raise QtWorkflowError("preview_stale")
            counted = []
            for approval in approvals:
                current = self.authorization.resolve(approval["user_id"], tx)
                if any(approval[name] != value for name, value in asdict(current).items()):
                    raise QtWorkflowError("authorization_changed")
                counted.append(current)
            if len(counted) > 1 or (counted and not self.authorization.quorum([*counted, person])):
                raise QtWorkflowError("approval_identity_unmapped")
            tx.insert_approval({"approval_id": str(uuid4()), "request_id": request_id, **asdict(person)})
            if self.authorization.quorum([*counted, person]):
                tx.promote_decision(decision["decision_id"])
            current_context = tx.get_override_context(request_id)
            public_approvals = []
            for approval in current_context["approvals"]:
                stamp = approval["approved_at"]
                if isinstance(stamp, datetime): stamp = stamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
                public_approvals.append({"person_id": approval["person_id"], "display_label": approval["person_id"].replace("_", " "),
                                         "user_id": str(approval["user_id"]), "approved_at": stamp})
            response = QtDecisionResponse.from_wire({"schema_version": SCHEMA_VERSION, "book_id": book_id,
                "preview_id": str(decision["preview_id"]), "decision_id": str(decision["decision_id"]), "request_id": request_id,
                "status": current_context["decision"]["status"], "selected_book_digest": decision["selected_book_digest"],
                "read_set_digest": decision["read_set_digest"], "approvals": public_approvals, "approvals_count": len(public_approvals),
                "required_approvals": 2, "can_approve": False, "receipt": None, "report_ready": False,
                "report_blocked_reasons": ["desk_receipt_pending"]})
            tx.insert_idempotent("approve_override", request_id, request.idempotency_key, request_digest, response.to_wire())
            return response
