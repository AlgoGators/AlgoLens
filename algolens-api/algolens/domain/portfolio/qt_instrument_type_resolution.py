"""Instrument asset-type resolution: catalog authority with a registry fallback.

When the catalog (metadata.contract_metadata) has no row for a symbol, the
key's own registered strategy's asset_class (trading.strategy_registry) is an
acceptable fallback -- resolved per key, from that key's own registry row
only (joined on trading.strategy_registry.strategy_type, which is what a
position/draft key's strategy_id actually names -- trading.strategy_registry.id
is that row's own separate primary key, not the join field), never unioned
or inherited across the other strategies reachable for the same book. The
catalog remains authoritative whenever it has an answer; a disagreement
between the two authorities is untrustworthy and is never adjudicated by
picking one. A strategy with no declared asset_class, an unrecognized
asset_class, a missing registry row for the key's strategy_type, or
conflicting registry rows for the same strategy_type, never resolves
either -- that key fails closed unless the catalog already answered it.
Pure: no I/O, no network reach.
"""

from collections.abc import Mapping, Sequence


from algolens.domain.portfolio.position_edit import PositionValidationError


#: Mirrors algolens.infrastructure.portfolio.instrument_catalog._TYPES. Kept
#: as its own copy: this module is domain and must not import infrastructure.
_TYPES = {"FUTURE": "FUTURE", "FUT": "FUTURE", "FUTURES": "FUTURE",
          "EQUITY": "EQUITY", "STK": "EQUITY"}


def _unavailable():
    return PositionValidationError(
        "instrument_type_unavailable", "Instrument type could not be verified")


def _conflict():
    return PositionValidationError(
        "instrument_type_conflict",
        "Catalog and the registered strategy's asset class disagree on instrument type")


def resolve_asset_type(catalog_kind, registry_kind):
    """Apply the precedence the user decided.

    catalog_kind / registry_kind are each None or an already-normalized kind
    ('FUTURE' / 'EQUITY'). The catalog wins when it has an answer and the
    registry has none, and also when both are present and agree; the
    registry is consulted (as a fallback) only when the catalog is silent.
    A conflict -- both present and disagreeing -- is never adjudicated by
    picking one: it fails closed with the same exception as the neither
    case (both absent, including an ambiguous or missing registry entry),
    matching the existing "instrument type unavailable"/"instrument type
    conflict" refusals.
    """
    if catalog_kind is not None:
        if registry_kind is not None and registry_kind != catalog_kind:
            raise _conflict()
        return catalog_kind
    if registry_kind is not None:
        return registry_kind
    raise _unavailable()


def _normalized(raw):
    if not isinstance(raw, str) or not raw.strip():
        return None
    return _TYPES.get(raw.strip().upper())


def registry_asset_class(registries):
    """Each registered strategy's own single declared asset_class, keyed by
    its strategy_type -- the value a position/draft key's strategy_id names.

    `registries` is the sequence of locked trading.strategy_registry rows
    reachable for the book (the same rows QtTransaction.lock_registries
    returns under the lock the proposal already takes; a book can reach more
    than one registry row through direct ownership and through
    strategy_book_memberships -- possibly more than one row per
    strategy_type, for example an old retired row alongside a current one),
    each row carrying a 'strategy_type' (the engine identity a key's
    strategy_id equals -- NOT the row's own 'id' primary key, which is a
    separate, UI-facing identifier) and an optional 'asset_class' column
    value.

    Returns a mapping from strategy_type to that strategy's single
    recognized asset_class. This is `qt_workflow.py._validate_catalog`'s own
    type gate (`qt_workflow.py:324-326`, `owners = self._book_owners(...)`,
    `len(owners) != 1` refuses regardless of status, and active+live is
    required only when the row is editable) -- NOT `_preview_access`'s or
    `save_draft`'s stricter *ownership* rule, which additionally requires
    active+live and a membership row, but only for a row that is actually
    being edited. A strategy_type gets an entry only when EXACTLY ONE
    reachable row here has that strategy_type -- any is_active or lifecycle,
    including 'retired' or 'incubating' (migration 002's real lifecycle
    values; an immutable row under a single retired or incubating owner is
    explicitly allowed, matching `_validate_catalog`) -- and that one row
    declares a recognized asset_class. Every other shape has no entry,
    resolved PER STRATEGY_TYPE, never unioned or agreed across the other
    rows reachable for the same book:
      - zero rows for that strategy_type (unknown or missing strategy);
      - two or more reachable rows for that strategy_type, EVEN IF they
        agree on the same class and regardless of is_active/lifecycle --
        ownership identity itself must be unambiguous first, exactly as
        `_validate_catalog`'s `len(owners) != 1` check requires, so two
        agreeing rows (active or not) are refused rather than guessed;
      - the (single) row's own asset_class is NULL or unrecognized.
    Callers look a key's fallback up by `.get(key.strategy_id)`: a missing
    entry means no fallback for that key -- it fails closed through
    `resolve_asset_type` unless the catalog already resolved it. A book
    whose OTHER registered strategies are ambiguous, conflicting or NULL
    never blocks a key whose OWN strategy has exactly one reachable row
    declaring exactly one class.

    This function does not, and must not, additionally require active+live:
    that is an EDITABLE-row ownership concern `_preview_access`, `save_draft`
    and `_validate_catalog` (for editable rows only) already enforce
    independently, downstream of instrument-type resolution. Duplicating it
    here would refuse legitimate immutable rows under a retired or
    incubating owner (independent review 1's finding 1, revision 2: an
    equity book with a futures-only catalog, one LIVE active+live EQUITY
    owner and one OLD retired EQUITY owner for a DIFFERENT strategy_type,
    used to refuse the whole batch even though both strategies each have
    exactly one owning row).
    """
    if not isinstance(registries, Sequence) or isinstance(registries, (str, bytes)):
        return {}
    by_type = {}
    for row in registries:
        if not isinstance(row, Mapping):
            continue
        strategy_type = row.get("strategy_type")
        if not isinstance(strategy_type, str) or not strategy_type:
            continue
        by_type.setdefault(strategy_type, []).append(row)
    result = {}
    for strategy_type, rows in by_type.items():
        if len(rows) != 1:
            continue
        kind = _normalized(rows[0].get("asset_class"))
        if kind is not None:
            result[strategy_type] = kind
    return result
