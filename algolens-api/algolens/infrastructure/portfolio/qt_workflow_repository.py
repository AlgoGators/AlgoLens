"""Scoped QT persistence with one transaction and a fixed global lock order.

Callers perform current authorization and source/read-set revalidation while
holding these locks. This module never publishes positions or results.
"""

from contextlib import contextmanager
from collections.abc import Callable, Iterable, Mapping
from typing import Any
from uuid import UUID
from datetime import date, datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json

from psycopg2 import Error as PostgresError
from psycopg2.extras import Json, RealDictCursor

from algolens.domain.portfolio.qt_workflow_errors import QtWorkflowError
from algolens.domain.portfolio.position_decimal import canonical_position_decimal8
from algolens.infrastructure.portfolio.book_lock import acquire_qt_book_locks
from algolens.infrastructure.portfolio.qt_provenance import reconcile_qt_source
from algolens.infrastructure.portfolio.instrument_catalog import _lookup, _ROLL_SYMBOL
from algolens.domain.portfolio.position_edit import PositionValidationError
from algolens.domain.portfolio.qt_instrument_type_resolution import resolve_asset_type


_INSERT_COLUMNS = {
    "qt_drafts": (
        "draft_id", "book_id", "source_day", "revision", "model_publication_id",
        "model_publication_version", "seed_digest", "source_digest", "provenance_digest",
        "draft_digest", "selection_payload", "created_by", "updated_by",
    ),
    "qt_previews": (
        "preview_id", "book_id", "source_day", "draft_id", "draft_revision",
        "draft_digest", "source_digest", "provenance_digest", "read_set_digest",
        "optimizer_book_digest", "selected_book_digest", "payload_digest", "payload",
        "read_set_payload", "evaluator_build", "policy_version", "availability",
        "created_by", "state",
    ),
    "qt_decisions": (
        "decision_id", "preview_id", "book_id", "source_day", "status",
        "model_publication_id", "provenance_digest", "draft_id", "draft_revision",
        "selected_book_digest", "read_set_digest", "workflow_capability_version",
        "submitter_grant_version", "policy_version", "payload", "created_by",
    ),
    "qt_override_requests": (
        "request_id", "decision_id", "eligibility_version", "required_approvals",
    ),
    "qt_override_approvals": (
        "approval_id", "request_id", "person_id", "user_id", "mapping_version",
        "grant_version",
    ),
}

_JSON_COLUMNS = {"selection_payload", "payload", "read_set_payload", "response_payload"}


class QtTransaction:
    """A transaction-scoped cursor that enforces auth→registry→book→mutable."""

    def __init__(self, cursor: Any, book_id: str, actor_id: int, *, recompute_client_factory=None,
                 finalization_recompute_client_factory=None):
        if not isinstance(book_id, str) or not book_id.strip() or type(actor_id) is not int or actor_id <= 0:
            raise ValueError("invalid_qt_transaction_scope")
        self.cursor = cursor
        self.book_id = book_id
        self.actor_id = actor_id
        if recompute_client_factory is not None and not callable(recompute_client_factory):
            raise ValueError('invalid_qt_recompute_factory')
        self._recompute_client_factory = recompute_client_factory
        if finalization_recompute_client_factory is not None and not callable(finalization_recompute_client_factory):
            raise ValueError('invalid_qt_finalization_recompute_factory')
        self._finalization_recompute_client_factory = finalization_recompute_client_factory
        self._stage = 0
        self._authorities = {}

    def _advance(self, expected: int) -> None:
        if self._stage != expected:
            raise RuntimeError("QT lock order violation")
        self._stage += 1

    def lock_authorities(self, user_ids: Iterable[int]) -> tuple[dict, ...]:
        self._advance(0)
        ids = sorted(set(user_ids) | {self.actor_id})
        if any(type(user_id) is not int or user_id <= 0 for user_id in ids):
            raise ValueError("invalid_qt_user_id")
        locked = []
        for user_id in ids:
            try:
                self.cursor.execute("SELECT id, role FROM auth.users WHERE id = %s FOR UPDATE", (user_id,))
            except PostgresError:
                raise QtWorkflowError("workflow_unavailable", "Current account authority is unavailable") from None
            row = self.cursor.fetchone()
            if row is None:
                raise QtWorkflowError("authorization_changed")
            locked.append(dict(row))
            self.cursor.execute(
                "SELECT user_id, capability, active, version FROM trading.qt_action_grants "
                "WHERE user_id = %s ORDER BY capability FOR UPDATE",
                (user_id,),
            )
            grants = [dict(item) for item in self.cursor.fetchall()]
            self.cursor.execute(
                "SELECT person_id, user_id, active, mapping_version "
                "FROM trading.qt_approver_allowlist WHERE user_id = %s "
                "ORDER BY person_id FOR UPDATE",
                (user_id,),
            )
            mappings = [dict(item) for item in self.cursor.fetchall()]
            self._authorities[user_id] = {"account": dict(row), "grants": grants, "mappings": mappings}
        return tuple(locked)

    def approval_authority(self, user_id: int) -> dict:
        self._require_mutable()
        if user_id not in self._authorities:
            raise QtWorkflowError("authorization_changed")
        return self._authorities[user_id]

    def lock_registries(self, registry_ids: Iterable[str]) -> tuple[dict, ...]:
        self._advance(1)
        locked = []
        for registry_id in sorted(set(registry_ids)):
            if not isinstance(registry_id, str) or not registry_id:
                raise ValueError("invalid_qt_registry_id")
            self.cursor.execute(
                "SELECT id, strategy_type, portfolio_id, is_active, lifecycle, asset_class FROM trading.strategy_registry "
                "WHERE id = %s FOR UPDATE",
                (registry_id,),
            )
            row = self.cursor.fetchone()
            if row is None:
                raise QtWorkflowError("authorization_changed")
            locked.append(dict(row))
        return tuple(locked)

    def registry_ids_for_book(self) -> tuple[str, ...]:
        if self._stage != 1:
            raise RuntimeError("QT registry discovery outside ordered locks")
        self.cursor.execute(
            "SELECT id FROM trading.strategy_registry WHERE portfolio_id = %s OR id IN "
            "(SELECT strategy_id FROM trading.strategy_book_memberships WHERE portfolio_id = %s) "
            "ORDER BY id", (self.book_id, self.book_id),
        )
        return tuple(row["id"] for row in self.cursor.fetchall())

    def lock_books(self, book_ids: Iterable[str]) -> None:
        self._advance(2)
        books = set(book_ids)
        books.add(self.book_id)
        acquire_qt_book_locks(self.cursor, *books)

    def utc_source_day(self) -> date:
        if self._stage != 3:
            raise RuntimeError("QT day sampled before book lock")
        self.cursor.execute("SELECT (clock_timestamp() AT TIME ZONE 'UTC')::date AS source_day")
        value = self.cursor.fetchone()["source_day"]
        return date.fromisoformat(value) if isinstance(value, str) else value

    def lock_mutable(self, *, source_day=None, preview_ids=(), decision_ids=(),
                     request_ids=(), approval_ids=(), receipt_decision_ids=()) -> None:
        self._advance(3)
        # The book advisory lock serializes absent rows as well as existing rows.
        # Lock only the selected mutable rows, in table and stable-ID order.
        if source_day is not None:
            self.cursor.execute(
                "SELECT draft_id FROM trading.qt_draft_heads "
                "WHERE book_id = %s AND source_day = %s FOR UPDATE",
                (self.book_id, source_day),
            )
            self.cursor.fetchone()  # An absent head is valid for the first revision.
        targets = (
            (preview_ids, "SELECT preview_id FROM trading.qt_previews WHERE book_id = %s AND preview_id = %s FOR UPDATE"),
            (decision_ids, "SELECT decision_id FROM trading.qt_decisions WHERE book_id = %s AND decision_id = %s FOR UPDATE"),
            (request_ids, "SELECT r.request_id FROM trading.qt_override_requests r JOIN trading.qt_decisions d ON d.decision_id = r.decision_id WHERE d.book_id = %s AND r.request_id = %s FOR UPDATE OF r"),
            (approval_ids, "SELECT a.approval_id FROM trading.qt_override_approvals a JOIN trading.qt_override_requests r ON r.request_id = a.request_id JOIN trading.qt_decisions d ON d.decision_id = r.decision_id WHERE d.book_id = %s AND a.approval_id = %s FOR UPDATE OF a"),
            (receipt_decision_ids, "SELECT c.decision_id FROM trading.qt_desk_receipts c JOIN trading.qt_decisions d ON d.decision_id = c.decision_id WHERE d.book_id = %s AND c.decision_id = %s FOR UPDATE OF c"),
        )
        for ids, query in targets:
            for row_id in sorted({str(value) for value in ids}):
                self.cursor.execute(query, (self.book_id, row_id))
                if self.cursor.fetchone() is None:
                    raise QtWorkflowError("authorization_changed")

    def _require_mutable(self) -> None:
        if self._stage != 4:
            raise RuntimeError("QT mutation before ordered locks")

    def capability(self) -> dict:
        self._require_mutable()
        self.cursor.execute(
            "SELECT book_id, enabled, version FROM trading.qt_workflow_capabilities WHERE book_id = %s",
            (self.book_id,),
        )
        row = self.cursor.fetchone()
        if row is None:
            raise QtWorkflowError("workflow_unavailable")
        return dict(row)

    def read_source_evidence(self) -> dict[str, object]:
        """Read complete day/book source evidence within the locked transaction.

        The wall clock is sampled only after the ordered lock stages. Absence
        and malformed producer metadata are passed to reconciliation, which
        must refuse to label an unproven proposal as MODEL-origin.
        """
        self._require_mutable()
        self.cursor.execute(
            "WITH sampled AS (SELECT clock_timestamp() AS captured_at) "
            "SELECT captured_at, (captured_at AT TIME ZONE 'UTC')::date AS source_day "
            "FROM sampled"
        )
        clock = dict(self.cursor.fetchall()[0])
        day = clock["source_day"]
        if isinstance(day, str):
            day = date.fromisoformat(day)
        captured = clock["captured_at"]
        if isinstance(captured, datetime):
            captured = captured.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        if not isinstance(captured, str) or not captured.endswith("Z"):
            raise ValueError("invalid_transaction_clock")
        rows = {}
        for stream in ("qt_proposal", "qt", "system"):
            revision_column = (
                "qt_proposal_revision AS position_revision" if stream == "qt_proposal"
                else "NULL::uuid AS position_revision"
            )
            self.cursor.execute(
                "SELECT portfolio_id, strategy_id, strategy_name, date, symbol, portfolio_type, "
                "quantity::text AS quantity_exact, average_price::text AS average_price_exact, "
                + revision_column + " FROM trading.positions "
                "WHERE portfolio_id = %s AND date = %s AND portfolio_type = %s "
                "ORDER BY portfolio_id, strategy_id, strategy_name, date, symbol, portfolio_type",
                (self.book_id, day, stream),
            )
            parsed = []
            for raw in self.cursor.fetchall():
                record = dict(raw)
                key = {name: record[name] for name in (
                    "portfolio_id", "strategy_id", "strategy_name", "date", "symbol", "portfolio_type")}
                if isinstance(key["date"], date):
                    key["date"] = key["date"].isoformat()
                position = {
                    "key": key,
                    "quantity_exact": canonical_position_decimal8(Decimal(record["quantity_exact"])),
                    "average_price_exact": canonical_position_decimal8(Decimal(record["average_price_exact"])),
                }
                if stream == "qt_proposal":
                    revision = record["position_revision"]
                    position["position_revision"] = str(revision) if revision is not None else None
                parsed.append(position)
            rows[stream] = parsed
        self.cursor.execute(
            "SELECT publication_id, attempt_id, portfolio_id, strategy_id, source_day, "
            "publication_version, system_components, seed_digest, producer_version, "
            "proposal_components, proposal_manifest_digest "
            "FROM trading.qt_model_seed_publications "
            "WHERE portfolio_id = %s AND source_day = %s "
            "ORDER BY publication_version, publication_id",
            (self.book_id, day),
        )
        publications = []
        for raw in self.cursor.fetchall():
            item = dict(raw)
            for name in ("publication_id", "attempt_id"):
                if item[name] is not None:
                    item[name] = str(item[name])
            publications.append(item)
        from algolens.infrastructure.portfolio.qt_empty_owner_sql import load_current_model_publications
        publications = load_current_model_publications(self, day, publications)
        self.cursor.execute(
            "SELECT o.id, o.user_id, o.portfolio_id, o.strategy_id, o.symbol, o.source_app, "
            "o.before_state, o.after_state, to_jsonb(o)->'risk_check_result' AS risk_check_result, "
            "s.portfolio_id AS legacy_scope_book "
            "FROM trading.position_overrides o "
            "LEFT JOIN trading.position_override_legacy_scopes s ON s.override_id = o.id "
            "WHERE o.portfolio_id = %s OR s.portfolio_id = %s "
            "ORDER BY o.id",
            (self.book_id, self.book_id),
        )
        audits = [dict(item) for item in self.cursor.fetchall()]
        saved_accounting = self.read_saved_accounting(day)
        processed = self.read_processed_publications(day)
        return {
            "captured_at": captured, "source_day": day,
            "source_rows": rows["qt_proposal"], "saved_rows": rows["qt"],
            "system_rows": rows["system"], "publications": publications,
            "audits": audits,
            "saved_accounting": saved_accounting, "processed_publications": processed,
        }

    def read_processed_publications(self, source_day: date) -> list[dict[str, object]]:
        """Actual scoped immutable links; missing referenced evidence remains missing."""
        self._require_mutable()
        self.cursor.execute("SELECT r.decision_id FROM trading.qt_desk_receipts r JOIN trading.qt_decisions d "
                            "ON d.decision_id=r.decision_id WHERE d.book_id=%s AND d.source_day=%s AND r.status='processed' "
                            "ORDER BY r.processed_at,r.decision_id", (self.book_id, source_day))
        if not self.cursor.fetchall():
            return []
        self.cursor.execute("SELECT to_jsonb(d) AS decision,to_jsonb(p) AS preview,to_jsonb(r) AS receipt, "
                            "to_jsonb(o) AS observation,to_jsonb(y) AS result FROM trading.qt_desk_receipts r "
                            "JOIN trading.qt_decisions d ON d.decision_id=r.decision_id "
                            "JOIN trading.qt_previews p ON p.preview_id=d.preview_id "
                            "LEFT JOIN trading.qt_execution_observations o ON o.decision_id=d.decision_id "
                            "AND o.observation_id::text=r.publication_payload->>'observation_id' "
                            "LEFT JOIN trading.qt_desk_results y ON y.decision_id=d.decision_id "
                            "AND y.attempt_id=r.attempt_id AND y.observation_id=o.observation_id "
                            "WHERE d.book_id=%s AND d.source_day=%s AND r.status='processed' "
                            "ORDER BY r.processed_at,r.decision_id", (self.book_id, source_day))
        records = []
        for raw in self.cursor.fetchall():
            evidence = dict(raw)
            from algolens.infrastructure.portfolio.qt_accounting_proof import load_accounting_evidence
            evidence["accounting"] = load_accounting_evidence(self.cursor, evidence["decision"],
                evidence["receipt"]["publication_payload"]["observation_id"])
            for name in ("receipt", "observation"):
                row = evidence[name]
                if row is None: continue
                for field in ("as_of", "valid_until", "processed_at"):
                    value = row.get(field)
                    if isinstance(value, str):
                        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                        if parsed.tzinfo is not None:
                            row[field] = parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            records.append(evidence)
        return records

    def read_current_facts(self, *, actor_id: int | None = None) -> dict[str, object]:
        """Select a closed read-set from the same locked transaction.

        Existing risk publications are inventoried for stale detection but do
        not become an approved QT risk policy. No current governed market,
        cost, quantity-rule, or portfolio-capital source is wired here.
        """
        grant_actor = self.actor_id if actor_id is None else actor_id
        if type(grant_actor) is not int or grant_actor <= 0:
            raise ValueError("invalid_qt_user_id")
        source = self.read_source_evidence()
        day = source["source_day"]

        def utc_text(value):
            if isinstance(value, datetime):
                return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            return value

        def json_digest(value):
            wire = json.dumps(value, sort_keys=True, separators=(",", ":"),
                              ensure_ascii=False, allow_nan=False).encode("utf-8", "strict")
            if len(wire) > 1_048_576:
                raise ValueError("oversize_source_json")
            return sha256(wire).hexdigest()

        self.cursor.execute(
            "SELECT id, strategy_type, portfolio_id, is_active, lifecycle, updated_at "
            "FROM trading.strategy_registry WHERE portfolio_id = %s OR id IN "
            "(SELECT strategy_id FROM trading.strategy_book_memberships WHERE portfolio_id = %s) "
            "ORDER BY id", (self.book_id, self.book_id),
        )
        registry = [{**dict(row), "updated_at": utc_text(row["updated_at"])}
                    for row in self.cursor.fetchall()]
        self.cursor.execute(
            "SELECT strategy_id, portfolio_id FROM trading.strategy_book_memberships "
            "WHERE portfolio_id = %s ORDER BY strategy_id, portfolio_id", (self.book_id,),
        )
        memberships = [dict(row) for row in self.cursor.fetchall()]
        self.cursor.execute(
            "SELECT enabled, version FROM trading.qt_workflow_capabilities "
            "WHERE book_id = %s", (self.book_id,),
        )
        capability_row = self.cursor.fetchone()
        capability = ({"status": "present", **dict(capability_row)} if capability_row is not None
                      else {"status": "absent", "enabled": None, "version": None})
        self.cursor.execute(
            "SELECT user_id, capability, active, version FROM trading.qt_action_grants "
            "WHERE user_id = %s ORDER BY capability", (grant_actor,),
        )
        grants = [{**dict(row), "user_id": str(row["user_id"])}
                  for row in self.cursor.fetchall()]
        self.cursor.execute(
            "SELECT h.draft_id, h.revision, d.draft_digest "
            "FROM trading.qt_draft_heads h JOIN trading.qt_drafts d "
            "ON d.draft_id = h.draft_id AND d.book_id = h.book_id "
            "AND d.source_day = h.source_day AND d.revision = h.revision "
            "WHERE h.book_id = %s AND h.source_day = %s", (self.book_id, day),
        )
        draft_row = self.cursor.fetchone()
        draft = ({"status": "present", "draft_id": str(draft_row["draft_id"]),
                  "revision": draft_row["revision"], "digest": draft_row["draft_digest"]}
                 if draft_row is not None else
                 {"status": "absent", "draft_id": None, "revision": 0, "digest": None})
        self.cursor.execute(
            "SELECT id, strategy_id, published_at, limits FROM trading.risk_limits "
            "WHERE portfolio_id = %s ORDER BY strategy_id, published_at, id", (self.book_id,),
        )
        risk_inventory = [{"id": row["id"], "strategy_id": row["strategy_id"],
                           "published_at": utc_text(row["published_at"]),
                           "content_digest": json_digest(row["limits"])}
                          for row in self.cursor.fetchall()]
        provenance = reconcile_qt_source(
            self.book_id, day, source["publications"], source["source_rows"], source["audits"],
            observed_saved_rows=source["saved_rows"],
            observed_system_rows=source["system_rows"],
            observed_saved_accounting=source["saved_accounting"],
            processed_publications=source["processed_publications"],
            recompute_client_factory=self._recompute_client_factory,
            finalization_recompute_client_factory=self._finalization_recompute_client_factory,
        )
        from algolens.infrastructure.portfolio.qt_empty_owner_sql import OwnerPublication, owner_publication_reference
        publications = [owner_publication_reference(row) if type(row) is OwnerPublication else
                        {"publication_id": str(row["publication_id"]),
                         "strategy_id": row["strategy_id"],
                         "publication_version": row["publication_version"],
                         "seed_digest": row["seed_digest"],
                         "proposal_manifest_digest": row.get("proposal_manifest_digest"),
                         "producer_version": row["producer_version"]}
                        for row in source["publications"]]
        audit_refs = [{"id": row["id"],
                       "user_id": str(row["user_id"]) if row["user_id"] is not None else None,
                       "source_app": row["source_app"],
                       "strategy_id": row["strategy_id"], "symbol": row["symbol"],
                       "before_digest": json_digest(row["before_state"]),
                       "after_digest": json_digest(row["after_state"])}
                      for row in source["audits"]]
        external_names = (
            "mark", "history", "cost", "multiplier", "universe",
            "instrument_type", "quantity_rule", "evaluator_policy",
        )
        return {
            "schema_version": "qt-read-set/v1", "book_id": self.book_id,
            "source_day": day.isoformat(), "captured_at": source["captured_at"],
            "source_rows": source["source_rows"], "saved_rows": source["saved_rows"],
            "saved_accounting": source["saved_accounting"],
            "system_rows": source["system_rows"], "publication_refs": publications,
            "audit_refs": audit_refs, "draft": draft, "registry": registry,
            "memberships": memberships, "capability": capability, "grants": grants,
            "risk_limits": {"status": "absent", "id": None, "published_at": None,
                            "content_digest": None},
            "risk_inventory": risk_inventory,
            "portfolio_inputs": {"status": "absent", "source_id": None,
                                 "source_day": None, "capital_exact": None,
                                 "content_digest": None},
            "external_sources": [{"name": name, "status": "unavailable",
                                  "source_id": None, "version": None, "as_of": None,
                                  "valid_until": None, "digest": None,
                                  "reason": "no_authoritative_versioned_source"}
                                 for name in external_names],
            "evaluator": {"status": "unavailable", "build": None,
                          "policy_version": None},
            "provenance": {"status": provenance.status,
                           "source_digest": provenance.observed_source_digest,
                           "chain_digest": provenance.legacy_audit_chain_digest,
                           "seed_digest": provenance.seed_digest},
        }

    def read_saved_accounting(self, source_day: date) -> list[dict[str, object]]:
        """Capture real saved QT accounting; absent fields remain unavailable."""
        self._require_mutable()
        self.cursor.execute(
            "SELECT portfolio_id, strategy_id, strategy_name, date, symbol, portfolio_type, "
            "quantity::text AS quantity_exact, average_price::text AS average_price_exact, "
            "to_jsonb(p)->>'daily_unrealized_pnl' AS daily_unrealized_pnl_exact, "
            "to_jsonb(p)->>'daily_realized_pnl' AS daily_realized_pnl_exact, "
            "to_jsonb(p)->>'last_update' AS last_update FROM trading.positions p "
            "WHERE portfolio_id = %s AND date = %s AND portfolio_type = 'qt' "
            "ORDER BY portfolio_id, strategy_id, strategy_name, date, symbol, portfolio_type",
            (self.book_id, source_day),
        )
        records = []
        for raw in self.cursor.fetchall():
            row = dict(raw)
            names = ("quantity_exact", "average_price_exact", "daily_unrealized_pnl_exact", "daily_realized_pnl_exact")
            if any(row.get(name) is None for name in (*names, "last_update")):
                continue
            try:
                stamp = datetime.fromisoformat(row["last_update"].replace("Z", "+00:00"))
                if stamp.tzinfo is None:
                    continue
                key = {name: row[name] for name in ("portfolio_id", "strategy_id", "strategy_name", "date", "symbol", "portfolio_type")}
                if isinstance(key["date"], date):
                    key["date"] = key["date"].isoformat()
                records.append({"key": key,
                    **{name: canonical_position_decimal8(Decimal(row[name])) for name in names},
                    "last_update": stamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")})
            except (ValueError, TypeError, ArithmeticError):
                continue
        return records

    def get_idempotent(self, operation: str, scope_id: str, key: UUID | str, request_digest: str) -> dict | None:
        self._require_mutable()
        self.cursor.execute(
            "SELECT request_digest, response_payload FROM trading.qt_idempotency "
            "WHERE actor_id = %s AND book_id = %s AND operation = %s "
            "AND scope_id = %s AND idempotency_key = %s",
            (self.actor_id, self.book_id, operation, scope_id, str(key)),
        )
        row = self.cursor.fetchone()
        if row is None:
            return None
        if row["request_digest"] != request_digest:
            raise QtWorkflowError("idempotency_conflict")
        return dict(row["response_payload"])

    def insert_idempotent(self, operation: str, scope_id: str, key: UUID | str,
                          request_digest: str, response_payload: Mapping[str, object]) -> None:
        self._require_mutable()
        self.cursor.execute(
            "INSERT INTO trading.qt_idempotency "
            "(actor_id, book_id, operation, scope_id, idempotency_key, request_digest, response_payload) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (self.actor_id, self.book_id, operation, scope_id, str(key),
             request_digest, Json(dict(response_payload))),
        )

    def _insert(self, table: str, data: Mapping[str, object], id_column: str) -> str:
        self._require_mutable()
        allowed = _INSERT_COLUMNS[table]
        unknown = set(data) - set(allowed)
        if unknown:
            raise ValueError("unsupported_qt_storage_fields")
        if "book_id" in allowed and data.get("book_id") != self.book_id:
            raise QtWorkflowError("authorization_changed")
        columns = tuple(name for name in allowed if name in data)
        values = tuple(Json(data[name]) if name in _JSON_COLUMNS else data[name] for name in columns)
        names = ", ".join(columns)
        placeholders = ", ".join("%s" for _ in columns)
        self.cursor.execute(
            f"INSERT INTO trading.{table} ({names}) VALUES ({placeholders}) RETURNING {id_column}",
            values,
        )
        return str(self.cursor.fetchone()[id_column])

    def insert_draft_revision(self, data: Mapping[str, object]) -> str:
        return self._insert("qt_drafts", data, "draft_id")

    def get_draft_head(self, source_day: date) -> dict | None:
        self._require_mutable()
        self.cursor.execute(
            "SELECT d.book_id, d.draft_id, d.revision, d.source_digest, d.provenance_digest, "
            "d.draft_digest, d.selection_payload, d.model_publication_id, "
            "d.model_publication_version, d.seed_digest "
            "FROM trading.qt_draft_heads h JOIN trading.qt_drafts d "
            "ON d.draft_id = h.draft_id AND d.book_id = h.book_id "
            "AND d.source_day = h.source_day AND d.revision = h.revision "
            "WHERE h.book_id = %s AND h.source_day = %s",
            (self.book_id, source_day),
        )
        row = self.cursor.fetchone()
        return dict(row) if row is not None else None

    def advance_draft_head(self, source_day: date, expected_revision: int,
                           draft_id: str, revision: int) -> None:
        self._require_mutable()
        if revision != expected_revision + 1:
            raise ValueError("invalid_qt_draft_revision")
        if expected_revision == 0:
            self.cursor.execute(
                "INSERT INTO trading.qt_draft_heads (book_id, source_day, draft_id, revision) "
                "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING RETURNING draft_id",
                (self.book_id, source_day, draft_id, revision),
            )
        else:
            self.cursor.execute(
                "UPDATE trading.qt_draft_heads SET draft_id = %s, revision = %s "
                "WHERE book_id = %s AND source_day = %s AND revision = %s RETURNING draft_id",
                (draft_id, revision, self.book_id, source_day, expected_revision),
            )
        if self.cursor.fetchone() is None:
            raise QtWorkflowError("draft_stale")

    def resolve_instrument_types(self, keys: Iterable[object], registry_asset_class: Mapping[str, str] | None = None) -> dict:
        """Resolve each key's asset type from the catalog, falling back --
        PER KEY, from that key's own strategy's registry row only -- to
        `registry_asset_class` only when the catalog has no row.

        `registry_asset_class` is the mapping domain.portfolio
        .qt_instrument_type_resolution.registry_asset_class returns: a
        registered strategy's strategy_type (== a key's strategy_id; NOT the
        registry row's own 'id' primary key) to that strategy's single
        declared asset_class, present only when that strategy_type has
        exactly one reachable registry row (any is_active/lifecycle --
        `_validate_catalog`'s own type-gate rule, qt_workflow.py:324-326;
        active+live is a separate, editable-row-only ownership concern
        `_preview_access`/`save_draft`/`_validate_catalog` enforce on their
        own) declaring a recognized class. A key is looked up by its own
        strategy_id (`registry_asset_class.get(key.strategy_id)`); a key
        whose strategy_id has no entry -- a NULL or unrecognized class, zero
        or several reachable rows (even several agreeing ones -- ownership
        identity itself must be unambiguous first), or a missing/unknown
        strategy_type for THAT strategy -- gets no fallback, regardless of
        what any other strategy in the same book declares. `registry_asset_class`
        is optional, and None (or anything that is not a mapping) means no
        fallback for every key, so existing callers that do not pass it keep
        their exact prior behavior."""
        self._require_mutable()
        fallback = registry_asset_class if isinstance(registry_asset_class, Mapping) else {}
        resolved = {}
        for key in sorted(set(keys)):
            try:
                kind = _lookup(self.cursor, key.symbol)
                if kind is None:
                    roll = _ROLL_SYMBOL.fullmatch(key.symbol)
                    if roll is not None and _lookup(self.cursor, roll.group(1)) == "FUTURE":
                        kind = "FUTURE"
                kind = resolve_asset_type(kind, fallback.get(key.strategy_id))
            except (PositionValidationError, PostgresError):
                raise QtWorkflowError("draft_identity_unresolved", "QT instrument type is unavailable") from None
            resolved[key] = kind
        return resolved

    def insert_preview(self, data: Mapping[str, object]) -> str:
        return self._insert("qt_previews", data, "preview_id")

    def get_preview(self, preview_id: UUID | str) -> dict | None:
        self._require_mutable()
        self.cursor.execute("SELECT * FROM trading.qt_previews WHERE book_id=%s AND preview_id=%s",
                            (self.book_id, str(preview_id)))
        row = self.cursor.fetchone()
        return dict(row) if row is not None else None

    def read_evaluation_policy(self) -> dict | None:
        self._require_mutable()
        self.cursor.execute("SELECT enabled,version,policy_version,allowed_override_codes FROM trading.qt_source_policies "
                            "WHERE book_id=%s AND purpose='evaluation'", (self.book_id,))
        row = self.cursor.fetchone()
        return dict(row) if row is not None else None

    def consume_preview(self, preview_id: UUID | str, expected_state: str, new_state: str) -> None:
        self._require_mutable()
        if expected_state != "pending" or new_state not in {"confirmed_decision", "pending_override"}:
            raise ValueError("invalid_qt_preview_transition")
        self.cursor.execute("UPDATE trading.qt_previews SET state=%s WHERE book_id=%s AND preview_id=%s "
                            "AND state=%s RETURNING preview_id", (new_state, self.book_id, str(preview_id), expected_state))
        if self.cursor.fetchone() is None:
            raise QtWorkflowError("preview_consumed")

    def insert_decision(self, data: Mapping[str, object]) -> str:
        return self._insert("qt_decisions", data, "decision_id")

    def insert_override_request(self, data: Mapping[str, object]) -> str:
        self._require_mutable()
        self.cursor.execute(
            "SELECT 1 FROM trading.qt_decisions WHERE decision_id = %s AND book_id = %s",
            (data.get("decision_id"), self.book_id),
        )
        if self.cursor.fetchone() is None:
            raise QtWorkflowError("authorization_changed")
        return self._insert("qt_override_requests", data, "request_id")

    def insert_approval(self, data: Mapping[str, object]) -> str:
        self._require_mutable()
        self.cursor.execute(
            "SELECT 1 FROM trading.qt_override_requests r "
            "JOIN trading.qt_decisions d ON d.decision_id = r.decision_id "
            "WHERE r.request_id = %s AND d.book_id = %s",
            (data.get("request_id"), self.book_id),
        )
        if self.cursor.fetchone() is None:
            raise QtWorkflowError("authorization_changed")
        return self._insert("qt_override_approvals", data, "approval_id")

    def get_override_context(self, request_id: UUID | str) -> dict | None:
        self._require_mutable()
        self.cursor.execute("SELECT r.* FROM trading.qt_override_requests r JOIN trading.qt_decisions d "
                            "ON d.decision_id=r.decision_id WHERE d.book_id=%s AND r.request_id=%s",
                            (self.book_id, str(request_id)))
        request = self.cursor.fetchone()
        if request is None:
            return None
        self.cursor.execute("SELECT * FROM trading.qt_decisions WHERE book_id=%s AND decision_id=%s",
                            (self.book_id, request["decision_id"]))
        decision = self.cursor.fetchone()
        self.cursor.execute("SELECT approval_id,request_id,person_id,user_id,mapping_version,grant_version,approved_at "
                            "FROM trading.qt_override_approvals WHERE request_id=%s ORDER BY approval_id", (str(request_id),))
        return {"request": dict(request), "decision": dict(decision), "approvals": [dict(row) for row in self.cursor.fetchall()]}

    def promote_decision(self, decision_id: UUID | str) -> None:
        self._require_mutable()
        self.cursor.execute("UPDATE trading.qt_decisions SET status='confirmed_decision' WHERE book_id=%s "
                            "AND decision_id=%s AND status='pending_override' RETURNING decision_id",
                            (self.book_id, str(decision_id)))
        if self.cursor.fetchone() is None:
            raise QtWorkflowError("decision_not_publishable")
        self.cursor.execute("UPDATE trading.qt_previews p SET state='confirmed_decision' "
                            "FROM trading.qt_decisions d WHERE d.book_id=%s AND d.decision_id=%s "
                            "AND d.status='confirmed_decision' AND p.preview_id=d.preview_id "
                            "AND p.book_id=d.book_id AND p.state='pending_override' RETURNING p.preview_id",
                            (self.book_id, str(decision_id)))
        if self.cursor.fetchone() is None:
            raise QtWorkflowError("decision_not_publishable")

    def get_receipt(self, decision_id: UUID | str) -> dict | None:
        self._require_mutable()
        self.cursor.execute(
            "SELECT c.* FROM trading.qt_desk_receipts c "
            "JOIN trading.qt_decisions d ON d.decision_id = c.decision_id "
            "WHERE d.book_id = %s AND c.decision_id = %s",
            (self.book_id, str(decision_id)),
        )
        row = self.cursor.fetchone()
        return dict(row) if row is not None else None


class QtWorkflowRepository:
    def __init__(self, connection_factory: Callable[[], Any] | None = None, *, recompute_client_factory=None,
                 finalization_recompute_client_factory=None):
        if recompute_client_factory is not None and not callable(recompute_client_factory):
            raise ValueError('invalid_qt_recompute_factory')
        self._recompute_client_factory = recompute_client_factory
        if finalization_recompute_client_factory is not None and not callable(finalization_recompute_client_factory):
            raise ValueError('invalid_qt_finalization_recompute_factory')
        self._finalization_recompute_client_factory = finalization_recompute_client_factory
        if connection_factory is None:
            from algolens.infrastructure.db.postgres import get_db_connection
            connection_factory = get_db_connection
        self._connection_factory = connection_factory

    def preview_routing(self, preview_id: UUID | str) -> dict | None:
        """Discover immutable routing only; the ordered transaction rechecks it."""
        conn = self._connection_factory()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("SELECT preview_id,book_id,source_day FROM trading.qt_previews WHERE preview_id=%s",
                               (str(preview_id),))
                row = cursor.fetchone()
                return dict(row) if row is not None else None
        finally:
            conn.close()

    def override_routing(self, request_id: UUID | str) -> dict | None:
        """Discover immutable scope and already recorded accounts before authority locks."""
        conn = self._connection_factory()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("SELECT r.request_id,d.decision_id,d.preview_id,d.book_id,d.source_day,d.created_by "
                               "FROM trading.qt_override_requests r JOIN trading.qt_decisions d "
                               "ON d.decision_id=r.decision_id WHERE r.request_id=%s", (str(request_id),))
                row = cursor.fetchone()
                if row is None:
                    return None
                cursor.execute("SELECT approval_id,request_id,person_id,user_id,mapping_version,grant_version,approved_at "
                               "FROM trading.qt_override_approvals WHERE request_id=%s ORDER BY approval_id", (str(request_id),))
                return {**dict(row), "approvals": [dict(item) for item in cursor.fetchall()]}
        finally:
            conn.close()

    @contextmanager
    def transaction(self, book_id: str, actor_id: int):
        conn = self._connection_factory()
        try:
            conn.autocommit = False
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                transaction = QtTransaction(cursor, book_id, actor_id,
                    recompute_client_factory=self._recompute_client_factory,
                    finalization_recompute_client_factory=self._finalization_recompute_client_factory)
                yield transaction
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()
