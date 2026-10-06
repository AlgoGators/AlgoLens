"""Conservative, immutable proof of MODEL seed and proposal lineage."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from algolens.domain.portfolio.position_decimal import canonical_position_decimal8
from algolens.domain.portfolio.qt_canonical import qt_digest_v1
from algolens.domain.portfolio.qt_workflow_models import QtKey
from algolens.domain.portfolio.qt_workflow_errors import QtWorkflowError
from algolens.infrastructure.portfolio.qt_read_set import internal_snapshot_digest


@dataclass(frozen=True, order=True)
class QtExactPosition:
    key: QtKey
    quantity_exact: str
    average_price_exact: str

    def to_wire(self) -> dict[str, object]:
        return {
            "key": self.key.to_wire(),
            "quantity_exact": self.quantity_exact,
            "average_price_exact": self.average_price_exact,
        }


@dataclass(frozen=True)
class QtVerifiedQtEdit:
    source_key: QtKey
    target_key: QtKey
    audit_ids: tuple[int, ...]
    origin: str = "verified_qt_edit"


@dataclass(frozen=True)
class QtProvenance:
    model_publication_id: str | None
    model_publication_version: int | None
    seed_digest: str | None
    observed_source_digest: str | None
    legacy_audit_chain_digest: str | None
    status: str
    seed_rows: tuple[QtExactPosition, ...]
    draft_overlay: tuple[QtExactPosition, ...]
    reason: str | None = None
    verified_qt_edits: tuple[QtVerifiedQtEdit, ...] = ()
    receipt_links: tuple[Mapping[str, object], ...] = ()
    receipt_decisions: tuple[Mapping[str, object], ...] = ()
    empty_owner_choice: Mapping[str, object] | None = None


def _exact(value: object) -> str:
    if type(value) is str:
        canonical = canonical_position_decimal8(value)
        if canonical != value:
            raise ValueError("noncanonical_exact")
        return value
    if type(value) is Decimal or type(value) is int:
        return canonical_position_decimal8(value)
    raise ValueError("untrusted_exact")


def _position(value: Mapping[str, object], *, stream: str) -> QtExactPosition:
    if not isinstance(value, Mapping):
        raise ValueError("invalid_position")
    key_data = value.get("key", value)
    key = QtKey.from_wire({
        field: key_data[field] for field in
        ("portfolio_id", "strategy_id", "strategy_name", "date", "symbol", "portfolio_type")
    })
    if key.portfolio_type != stream:
        raise ValueError("wrong_stream")
    quantity = value.get("quantity_exact", value.get("quantity"))
    basis = value.get("average_price_exact", value.get("average_price"))
    return QtExactPosition(key, _exact(quantity), _exact(basis))


def _unique_positions(rows: Sequence[Mapping[str, object]], *, stream: str) -> tuple[QtExactPosition, ...]:
    if not isinstance(rows, (list, tuple)) or len(rows) > 4096:
        raise ValueError("invalid_set")
    parsed = tuple(sorted((_position(row, stream=stream) for row in rows), key=lambda row: row.key))
    if len({row.key for row in parsed}) != len(parsed):
        raise ValueError("duplicate_key")
    return parsed


def _target_key(key: QtKey) -> QtKey:
    return QtKey(**{**key.to_wire(), "portfolio_type": "qt_proposal"})


def _unresolved(reason: str, *, seed_rows=(), publication=None, observed_digest=None) -> QtProvenance:
    return QtProvenance(
        model_publication_id=str(publication["publication_id"]) if publication else None,
        model_publication_version=publication["publication_version"] if publication else None,
        seed_digest=publication["seed_digest"] if publication else None,
        observed_source_digest=observed_digest,
        legacy_audit_chain_digest=None,
        status="provenance_unresolved",
        seed_rows=tuple(seed_rows),
        draft_overlay=(),
        reason=reason,
    )


def verify_exact_proposal_audits(
    initial_rows: Sequence[Mapping[str, object]],
    audit_rows: Sequence[Mapping[str, object]],
) -> tuple[QtExactPosition, ...]:
    """Apply only exact, full-key proposal-stream audit transitions.

    This pure verifier cannot establish physical revision-token continuity;
    callers must prove that separately before admitting the result.
    """
    current = {row.key: row for row in _unique_positions(initial_rows, stream="qt_proposal")}
    if not isinstance(audit_rows, (list, tuple)) or len(audit_rows) > 4096:
        raise ValueError("invalid_audits")
    seen = set()
    for audit in sorted(audit_rows, key=lambda item: item["id"]):
        audit_id = audit["id"]
        if type(audit_id) is not int or audit_id <= 0 or audit_id in seen:
            raise ValueError("ambiguous_audit_order")
        seen.add(audit_id)
        before_state, after_state = audit["before_state"], audit["after_state"]
        if any(name not in state for state in (before_state, after_state)
               for name in ("quantity_exact", "average_price_exact")):
            raise ValueError("audit_exact_missing")
        before = _position(before_state, stream="qt_proposal")
        after = _position(after_state, stream="qt_proposal")
        if (before.key != after.key or current.get(before.key) != before
                or audit["portfolio_id"] != before.key.portfolio_id
                or audit["strategy_id"] != before.key.strategy_id
                or audit["symbol"] != before.key.symbol
                or audit["source_app"] not in {"algolens", "manual_db_edit"}):
            raise ValueError("audit_chain_break")
        current[after.key] = after
    return tuple(current[key] for key in sorted(current))


def _verified_qt_overlay(book_id, day, proposal_keys, saved_rows, audits):
    from algolens.infrastructure.portfolio.qt_receipt_provenance import audit_is_other_qt_day
    saved = {row.key: row for row in _unique_positions(saved_rows, stream="qt")}
    proposals = set(proposal_keys)
    grouped = {}
    identities = {(key.strategy_id, key.symbol) for key in proposals}
    if not isinstance(audits, (list, tuple)) or len(audits) > 4096:
        raise ValueError("invalid_audits")
    seen_ids = set()
    for audit in sorted(audits, key=lambda item: item["id"]):
        related = (audit.get("strategy_id"), audit.get("symbol")) in identities
        related = related or any(
            isinstance(audit.get(state), Mapping)
            and (audit[state].get("strategy_id"), audit[state].get("symbol")) in identities
            for state in ("before_state", "after_state")
        )
        if not related:
            continue
        if audit_is_other_qt_day(audit, book_id, day):
            continue
        reference = audit.get("risk_check_result")
        if isinstance(reference, Mapping) and reference.get("schema_version") == "qt-desk-audit/v1":
            raise ValueError("receipt_proof_missing")
        before_state, after_state = audit["before_state"], audit["after_state"]
        before = _position(before_state, stream="qt")
        after = _position(after_state, stream="qt")
        if before.key.date != day.isoformat() and after.key.date != day.isoformat():
            continue
        audit_id = audit["id"]
        if (type(audit_id) is not int or audit_id <= 0 or audit_id in seen_ids
                or type(audit.get("user_id")) is not int or audit["user_id"] <= 0
                or audit.get("portfolio_id") != book_id
                or audit.get("source_app") not in {"algolens", "manual_db_edit"}
                or before.key != after.key
                or before.key.portfolio_id != book_id
                or before.key.strategy_id != audit["strategy_id"]
                or before.key.symbol != audit["symbol"]
                or any(field not in state for state in (before_state, after_state)
                       for field in ("quantity_exact", "average_price_exact"))):
            raise ValueError("untrusted_qt_audit")
        seen_ids.add(audit_id)
        target = _target_key(before.key)
        if target not in proposals or before.key not in saved:
            raise ValueError("unmapped_qt_edit")
        grouped.setdefault(before.key, []).append((audit_id, audit, before, after))
    overlay = []
    traces = []
    events = []
    for source_key, chain in sorted(grouped.items()):
        previous = None
        for audit_id, audit, before, after in chain:
            if previous is not None and previous != before:
                raise ValueError("qt_audit_chain_break")
            previous = after
            events.append({"id": audit_id, "user_id": str(audit["user_id"]),
                           "source_app": audit["source_app"],
                           "before": before.to_wire(), "after": after.to_wire()})
        if previous != saved[source_key]:
            raise ValueError("qt_audit_current_row_mismatch")
        target_key = _target_key(source_key)
        overlay.append(QtExactPosition(target_key, previous.quantity_exact,
                                       previous.average_price_exact))
        traces.append(QtVerifiedQtEdit(source_key, target_key,
                                       tuple(item[0] for item in chain)))
    return tuple(overlay), tuple(traces), events


def reconcile_qt_source(
    book_id: str,
    source_day: date,
    publications: Sequence[Mapping[str, object]] | None,
    observed_rows: Sequence[Mapping[str, object]],
    audit_rows: Sequence[Mapping[str, object]],
    *,
    observed_saved_rows: Sequence[Mapping[str, object]] = (),
    observed_system_rows: Sequence[Mapping[str, object]] | None = None,
    observed_saved_accounting: Sequence[Mapping[str, object]] = (),
    processed_publications: Sequence[Mapping[str, object]] = (),
    recompute_client_factory=None,
    finalization_recompute_client_factory=None,
) -> QtProvenance:
    """Prove an exact full-key chain, or return an unresolved typed result.

    A current physical revision must match an immutable inserted manifest
    entry and the latest complete manifest. Legacy qt audits do not prove a
    qt_proposal transition and are never relabelled.
    """
    if type(book_id) is not str or not book_id or type(source_day) is not date:
        return _unresolved("invalid_scope")
    if not isinstance(publications, (list, tuple)) or not publications:
        return _unresolved("publication_scope_missing_or_ambiguous")
    publication = publications[-1]
    try:
        versions = set()
        identities = set()
        for item in publications:
            version = item["publication_version"]
            identity = str(item["publication_id"])
            if (item["portfolio_id"] != book_id or item["source_day"] != source_day
                    or item["strategy_id"] != publication["strategy_id"]
                    or type(version) is not int or version <= 0 or version in versions
                    or str(UUID(identity)) != identity or identity in identities):
                return _unresolved("publication_scope_mismatch")
            versions.add(version)
            identities.add(identity)
        if publication["publication_version"] != max(versions):
            return _unresolved("publication_order_ambiguous")
        if publication.get('schema_version') == 'qt-empty-model-owner-publication/v2':
            return _reconcile_empty_owner(book_id, source_day, publications, observed_rows,
                audit_rows, observed_saved_rows, observed_system_rows, observed_saved_accounting)
        seed = _unique_positions(publication["system_components"], stream="system")
        if not seed or any(row.key.portfolio_id != book_id or row.key.date != source_day.isoformat()
                           or row.key.strategy_id != publication["strategy_id"] for row in seed):
            return _unresolved("seed_scope_mismatch")
        if qt_digest_v1({"seed_rows": [row.to_wire() for row in seed]}) != publication["seed_digest"]:
            return _unresolved("seed_digest_mismatch")
        if observed_system_rows is None:
            return _unresolved("current_system_rows_missing", seed_rows=seed,
                               publication=publication)
        current_system = _unique_positions(observed_system_rows, stream="system")
        if current_system != seed:
            return _unresolved("current_system_mismatch", seed_rows=seed,
                               publication=publication)
        observed = _unique_positions(observed_rows, stream="qt_proposal")
        if any(row.key.portfolio_id != book_id or row.key.date != source_day.isoformat() for row in observed):
            return _unresolved("proposal_scope_mismatch", seed_rows=seed, publication=publication)
        observed_digest = internal_snapshot_digest("qt-source/v1", {
            "schema_version": "qt-source/v1", "book_id": book_id,
            "source_day": source_day.isoformat(),
            "rows": [{**row.to_wire(), "position_revision": str(raw.get("position_revision"))
                      if raw.get("position_revision") is not None else None}
                     for row, raw in zip(observed, sorted(observed_rows,
                         key=lambda value: QtKey.from_wire(value["key"])))],
        })
        manifests = {}
        insertion = {}
        for item in publications:
            item_seed = _unique_positions(item["system_components"], stream="system")
            if (not item_seed or any(
                row.key.portfolio_id != book_id
                or row.key.date != source_day.isoformat()
                or row.key.strategy_id != item["strategy_id"] for row in item_seed
            ) or qt_digest_v1({"seed_rows": [row.to_wire() for row in item_seed]}) != item["seed_digest"]):
                raise ValueError("unproved_origin_seed")
            seed_by_proposal_key = {_target_key(row.key): row for row in item_seed}
            components = item["proposal_components"]
            manifest_digest = internal_snapshot_digest(
                "qt-proposal-manifest/v1", {"proposal_rows": components})
            if manifest_digest != item["proposal_manifest_digest"]:
                raise ValueError("manifest_digest_mismatch")
            manifest = {QtKey.from_wire(entry["key"]): entry for entry in components}
            if len(manifest) != len(components):
                raise ValueError("duplicate_manifest_key")
            manifests[str(item["publication_id"])] = manifest
            for key, entry in manifest.items():
                if entry["action"] == "inserted":
                    if entry["origin_publication_id"] != str(item["publication_id"]):
                        raise ValueError("foreign_insert_origin")
                    source = seed_by_proposal_key.get(key)
                    if (source is None or source.quantity_exact != entry["quantity_exact"]
                            or source.average_price_exact != entry["average_price_exact"]):
                        raise ValueError("insert_not_model_seed")
                    insertion[(str(item["publication_id"]), key)] = (
                        entry, item["publication_version"]
                    )
        for item in publications:
            for key, entry in manifests[str(item["publication_id"])].items():
                if entry["action"] != "preserved" or entry["origin_publication_id"] is None:
                    continue
                proof = insertion.get((entry["origin_publication_id"], key))
                if proof is None:
                    raise ValueError("preserved_origin_missing")
                origin, version = proof
                if (version >= item["publication_version"]
                        or origin["position_revision"] != entry["position_revision"]
                        or origin["quantity_exact"] != entry["quantity_exact"]
                        or origin["average_price_exact"] != entry["average_price_exact"]):
                    raise ValueError("preserved_history_break")
        latest_manifest = manifests[str(publication["publication_id"])]
        if len(latest_manifest) != len(observed) or len(seed) != len(observed):
            raise ValueError("incomplete_manifest")
        for source in seed:
            if _target_key(source.key) not in latest_manifest:
                raise ValueError("missing_seed_component")
        for row in observed_rows:
            proposal = _position(row, stream="qt_proposal")
            entry = latest_manifest[proposal.key]
            origin_id = entry["origin_publication_id"]
            proof = insertion.get((origin_id, proposal.key))
            origin = proof[0] if proof is not None else None
            if (origin is None or row.get("position_revision") is None
                    or entry["position_revision"] != str(row["position_revision"])
                    or origin["position_revision"] != entry["position_revision"]
                    or origin["quantity_exact"] != entry["quantity_exact"]
                    or origin["average_price_exact"] != entry["average_price_exact"]
                    or proposal.quantity_exact != entry["quantity_exact"]
                    or proposal.average_price_exact != entry["average_price_exact"]):
                raise ValueError("unproven_current_token")
            source = next(item for item in seed if _target_key(item.key) == proposal.key)
            if (source.quantity_exact != proposal.quantity_exact
                    or source.average_price_exact != proposal.average_price_exact):
                return _unresolved("changed_model_baseline", seed_rows=seed,
                                   publication=publication, observed_digest=observed_digest)
        from algolens.infrastructure.portfolio.qt_receipt_provenance import verified_receipt_chain
        receipt_proof = verified_receipt_chain(book_id, source_day, processed_publications, audit_rows,
            observed_saved_accounting, recompute_client_factory=recompute_client_factory,
            finalization_recompute_client_factory=finalization_recompute_client_factory)
        legacy_audits = audit_rows if receipt_proof is None else [row for row in audit_rows if row["id"] not in receipt_proof["audit_ids"]]
        legacy_saved = observed_saved_rows if receipt_proof is None else [
            {name: row[name] for name in ("key", "quantity_exact", "average_price_exact")}
            for row in receipt_proof["before"].values()]
        overlay, traces, audit_events = _verified_qt_overlay(
            book_id, source_day, {row.key for row in observed},
            legacy_saved, legacy_audits,
        )
        chain_digest = internal_snapshot_digest("qt-provenance/v1", {
            "schema_version": "qt-provenance/v1", "book_id": book_id,
            "source_day": source_day.isoformat(),
            "publication_id": str(publication["publication_id"]),
            "publication_version": publication["publication_version"],
            "seed_digest": publication["seed_digest"],
            "proposal_manifest_digest": publication["proposal_manifest_digest"],
            "audit_events": audit_events,
        })
        if receipt_proof is not None:
            receipt_overlay = tuple(QtExactPosition(_target_key(key), row["quantity_exact"], row["average_price_exact"])
                                    for key, row in sorted(receipt_proof["choices"].items()))
            overlay = tuple(sorted({**{row.key: row for row in overlay}, **{row.key: row for row in receipt_overlay}}.values(), key=lambda row: row.key))
            traces = tuple(trace for trace in traces if trace.target_key not in {row.key for row in receipt_overlay}) + tuple(
                QtVerifiedQtEdit(key, _target_key(key), tuple(audit["id"] for audit in sorted(audit_rows, key=lambda row: row["id"])
                    if audit["id"] in receipt_proof["audit_ids"] and isinstance(audit.get("after_state"), Mapping)
                    and all(audit["after_state"].get(name) == value for name, value in key.to_wire().items())),
                                 origin="verified_qt_decision") for key in sorted(receipt_proof["choices"]))
            chain_digest = internal_snapshot_digest("qt-receipt-provenance/v1", {
                "schema_version": "qt-receipt-provenance/v1", "book_id": book_id, "source_day": source_day.isoformat(),
                "legacy_chain_digest": chain_digest, "receipt_links": receipt_proof["links"]})
        return QtProvenance(
            str(publication["publication_id"]), publication["publication_version"],
            publication["seed_digest"], observed_digest, chain_digest, "ready", seed,
            overlay, verified_qt_edits=traces,
            receipt_links=receipt_proof["links"] if receipt_proof else (),
            receipt_decisions=receipt_proof["decisions"] if receipt_proof else (),
        )
    except (KeyError, TypeError, ValueError, AttributeError, IndexError, ArithmeticError, QtWorkflowError):
        return _unresolved("invalid_or_incomplete_lineage")


def _audit_inventory(rows):
    # Both actual SELECTs can attach extra SQL routing/timestamp columns. Bind
    # every original audit operand used by the chain; extras are not authority.
    fields = ('id', 'user_id', 'portfolio_id', 'strategy_id', 'symbol', 'source_app',
              'before_state', 'after_state', 'risk_check_result')
    return [{name: row.get(name) for name in fields} for row in rows]


def _reconcile_empty_owner(book, day, publications, observed, audits, saved, system, accounting):
    from algolens.infrastructure.portfolio.qt_empty_owner_sql import OwnerPublication, owner_publication_reference
    publication = publications[-1]
    if type(publication) is not OwnerPublication or not publication.current_inventory_verified:
        raise ValueError('current_owner_sql_proof_missing')
    current = publication.current_qt
    doc = publication.document
    # Canonical source/read-set validators remain shared with the v1 path.
    # These checks join this caller's complete SELECTs to the proved SQL rows.
    expected = [{name: row[name] for name in ('key','quantity_exact',
                'average_price_exact','position_revision')} for row in doc['proposal_components']]
    if (system != [] or observed != expected or saved != current['rows']
            or accounting != current['accounting']
            or _audit_inventory(audits) != _audit_inventory(current['source_audits'])):
        raise ValueError('owner_current_inventory_mismatch')
    source_digest = internal_snapshot_digest('qt-source/v1', dict(schema_version='qt-source/v1',
        book_id=book, source_day=day.isoformat(), rows=observed))
    # Empty MODEL output inserts no recommendation. Preserved proposal rows
    # retain a prior origin only after that origin's own nonempty v1 seed proof.
    inserted = {}
    for item in publications[:-1]:
        if item.get('schema_version') == 'qt-empty-model-owner-publication/v2':
            if type(item) is not OwnerPublication: raise ValueError('owner_archive_proof_missing')
            continue
        seed = _unique_positions(item['system_components'], stream='system')
        if (not seed or any(row.key.portfolio_id != book or row.key.date != day.isoformat()
            or row.key.strategy_id != item['strategy_id'] for row in seed)
            or qt_digest_v1({'seed_rows':[row.to_wire() for row in seed]}) != item['seed_digest']):
            raise ValueError('unproved_origin_seed')
        components = item['proposal_components']
        if internal_snapshot_digest('qt-proposal-manifest/v1', {'proposal_rows':components}) != item['proposal_manifest_digest']:
            raise ValueError('manifest_digest_mismatch')
        seeds = {_target_key(row.key):row for row in seed}
        for entry in components:
            if entry['action'] != 'inserted': continue
            key = QtKey.from_wire(entry['key']); original = seeds.get(key)
            if (entry['origin_publication_id'] != item['publication_id'] or original is None
                or (original.quantity_exact,original.average_price_exact) !=
                    (entry['quantity_exact'],entry['average_price_exact'])):
                raise ValueError('insert_not_model_seed')
            inserted[(item['publication_id'],key)] = (entry,item['publication_version'])
    for entry in doc['proposal_components']:
        proof = inserted.get((entry['origin_publication_id'],QtKey.from_wire(entry['key'])))
        if (entry['action'] != 'preserved' or proof is None
            or proof[1] >= publication['publication_version']
            or any(proof[0][name] != entry[name] for name in
                ('position_revision','quantity_exact','average_price_exact'))):
            raise ValueError('unproved_preserved_origin')
    chain = internal_snapshot_digest('qt-provenance/v1', dict(schema_version='qt-provenance/v1',
        book_id=book, source_day=day.isoformat(), publication_id=publication['publication_id'],
        publication_version=publication['publication_version'], seed_digest=publication['seed_digest'],
        proposal_manifest_digest=publication['proposal_manifest_digest'], audit_events=current['audit_events']))
    choice = None
    if not doc['proposal_components'] and not doc['qt_components'] and not current['rows'] and not current['accounting']:
        ref = owner_publication_reference(publication)
        choice = dict(schema_version='qt-empty-owner-choice/v2', model_publication_id=publication['publication_id'],
            owner_document_digest=ref['owner_document_digest'], configured_owner_names=ref['configured_owner_names'])
    if current['receipt_links']:
        empty_links=[row for row in current['receipt_links'] if 'processed_at' in row]
        if empty_links:
            if choice is None or len(empty_links)!=len(current['receipt_links']):
                raise ValueError('mixed_empty_owner_receipt_provenance')
            kind='qt-empty-owner-receipt-provenance/v2'
            chain=internal_snapshot_digest(kind,dict(schema_version=kind,book_id=book,source_day=day.isoformat(),
                legacy_chain_digest=chain,empty_owner=choice,receipt_links=current['receipt_links']))
        else:
            chain = internal_snapshot_digest('qt-receipt-provenance/v1', dict(
                schema_version='qt-receipt-provenance/v1', book_id=book, source_day=day.isoformat(),
                legacy_chain_digest=chain,receipt_links=current['receipt_links']))
    return QtProvenance(publication['publication_id'], publication['publication_version'],
        publication['seed_digest'], source_digest, chain, 'ready', (), current['overlay'],
        verified_qt_edits=current['traces'], receipt_links=current['receipt_links'],
        receipt_decisions=current['receipt_decisions'], empty_owner_choice=choice)
