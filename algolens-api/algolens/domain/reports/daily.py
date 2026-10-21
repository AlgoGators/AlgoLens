"""The daily trading report: the payload trade-ngin enqueues and the numbers derived from it.

Pure data and rules. How the report looks (HTML, charts) is infrastructure; what it says is here.
trade-ngin sends facts and flags (a holiday, a rollover) and never layout, so the calendar and
the wording stay on one side.
"""

from dataclasses import dataclass
from datetime import date

SCHEMA_VERSION = 1
NOTICE_KINDS = ("info", "holiday", "weekend", "warning")


class ReportPayloadError(ValueError):
    """A payload the report cannot be built from."""


@dataclass(frozen=True)
class Notice:
    kind: str
    title: str
    body: str
    footnote: str = ""


@dataclass(frozen=True)
class Position:
    symbol: str
    name: str
    quantity: float
    price: float
    notional: float
    weight: float | None = None


@dataclass(frozen=True)
class Execution:
    symbol: str
    side: str
    quantity: float
    price: float
    notional: float
    cost: float


@dataclass(frozen=True)
class RealizedPosition:
    symbol: str
    quantity: float
    entry_price: float
    exit_price: float
    pnl: float


@dataclass(frozen=True)
class Rollover:
    symbol: str
    current: str
    next: str


@dataclass(frozen=True)
class Metric:
    label: str
    value: str


@dataclass(frozen=True)
class DailyReport:
    report_date: date
    portfolio_id: str
    portfolio_name: str
    notices: tuple = ()
    positions: tuple = ()
    executions: tuple = ()
    realized_label: str = ""
    realized: tuple = ()
    metrics: tuple = ()
    equity: tuple = ()          # ((date label, value), ...)
    daily_pnl: tuple = ()       # ((date label, value), ...)
    pnl_by_symbol: tuple = ()   # ((symbol, value), ...)
    composition: tuple = ()     # ((label, value), ...)
    rollovers: tuple = ()
    footnotes: tuple = ()

    @property
    def total_notional(self):
        return sum(abs(p.notional) for p in self.positions)

    @property
    def total_realized_pnl(self):
        return sum(r.pnl for r in self.realized)

    @property
    def total_cost(self):
        return sum(e.cost for e in self.executions)

    @property
    def total_traded(self):
        return sum(abs(e.notional) for e in self.executions)


def _num(row, key, where):
    value = row.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ReportPayloadError(f"{where}.{key} must be a number")
    return float(value)


def _text(row, key, where, default=None):
    """A string field; required and non-empty unless a default is given."""
    value = row.get(key, default)
    if not isinstance(value, str) or (default is None and not value.strip()):
        raise ReportPayloadError(f"{where}.{key} must be a non-empty string")
    return value


def _rows(payload, key):
    value = payload.get(key, [])
    if not isinstance(value, list) or not all(isinstance(r, dict) for r in value):
        raise ReportPayloadError(f"{key} must be a list of objects")
    return value


def _series(series, key, label_key):
    return tuple(
        (_text(row, label_key, f"series.{key}[{i}]"), _num(row, "value", f"series.{key}[{i}]"))
        for i, row in enumerate(_rows(series, key))
    )


def _object(payload, key):
    value = payload.get(key) or {}
    if not isinstance(value, dict):
        raise ReportPayloadError(f"{key} must be an object")
    return value


def parse_daily_report(payload):
    """Validate a queue payload and build the report, or raise ReportPayloadError."""
    if not isinstance(payload, dict):
        raise ReportPayloadError("payload must be an object")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ReportPayloadError(f"schema_version must be {SCHEMA_VERSION}")
    try:
        report_date = date.fromisoformat(_text(payload, "report_date", "payload"))
    except ValueError as exc:
        raise ReportPayloadError("report_date must be YYYY-MM-DD") from exc

    notices = []
    for i, row in enumerate(_rows(payload, "notices")):
        where = f"notices[{i}]"
        kind = _text(row, "kind", where)
        if kind not in NOTICE_KINDS:
            raise ReportPayloadError(f"{where}.kind must be one of {', '.join(NOTICE_KINDS)}")
        notices.append(
            Notice(kind, _text(row, "title", where), _text(row, "body", where),
                   _text(row, "footnote", where, default=""))
        )

    positions = []
    for i, r in enumerate(_rows(payload, "positions")):
        where = f"positions[{i}]"
        weight = r.get("weight")
        positions.append(
            Position(_text(r, "symbol", where), _text(r, "name", where, default=""),
                     _num(r, "quantity", where), _num(r, "price", where),
                     _num(r, "notional", where),
                     float(weight) if isinstance(weight, (int, float)) else None)
        )

    executions = []
    for i, r in enumerate(_rows(payload, "executions")):
        where = f"executions[{i}]"
        executions.append(
            Execution(_text(r, "symbol", where), _text(r, "side", where).upper(),
                      _num(r, "quantity", where), _num(r, "price", where),
                      _num(r, "notional", where), _num(r, "cost", where))
        )

    realized_block = _object(payload, "realized")
    realized = []
    for i, r in enumerate(_rows(realized_block, "positions")):
        where = f"realized.positions[{i}]"
        realized.append(
            RealizedPosition(_text(r, "symbol", where), _num(r, "quantity", where),
                             _num(r, "entry_price", where), _num(r, "exit_price", where),
                             _num(r, "pnl", where))
        )

    metrics = tuple(
        Metric(_text(r, "label", f"metrics[{i}]"), _text(r, "value", f"metrics[{i}]"))
        for i, r in enumerate(_rows(payload, "metrics"))
    )
    rollovers = tuple(
        Rollover(_text(r, "symbol", f"rollovers[{i}]"), _text(r, "current", f"rollovers[{i}]"),
                 _text(r, "next", f"rollovers[{i}]"))
        for i, r in enumerate(_rows(payload, "rollovers"))
    )
    footnotes = payload.get("footnotes", [])
    if not isinstance(footnotes, list) or not all(isinstance(x, str) for x in footnotes):
        raise ReportPayloadError("footnotes must be a list of strings")
    series = _object(payload, "series")

    return DailyReport(
        report_date=report_date,
        portfolio_id=_text(payload, "portfolio_id", "payload"),
        portfolio_name=_text(payload, "portfolio_name", "payload"),
        notices=tuple(notices),
        positions=tuple(positions),
        executions=tuple(executions),
        realized_label=str(realized_block.get("label", "")),
        realized=tuple(realized),
        metrics=metrics,
        equity=_series(series, "equity", "date"),
        daily_pnl=_series(series, "daily_pnl", "date"),
        pnl_by_symbol=_series(series, "pnl_by_symbol", "symbol"),
        composition=_series(series, "composition", "label"),
        rollovers=rollovers,
        footnotes=tuple(footnotes),
    )


# --- presentation numbers (text only, no markup) -------------------------------------------


def money(value, places=0):
    """$1,234 or -$1,234."""
    sign = "-" if round(value, places) < 0 else ""
    return f"{sign}${abs(value):,.{places}f}"


def signed_money(value, places=0):
    """+$1,234 or -$1,234; a zero is shown plain."""
    if round(value, places) == 0:
        return money(0, places)
    return ("+" if value > 0 else "-") + f"${abs(value):,.{places}f}"


def compact_money(value):
    """$1.08M, $12k, $950: for axes and headline numbers."""
    sign = "-" if value < 0 else ""
    v = abs(value)
    if v >= 1_000_000:
        return f"{sign}${v / 1_000_000:.2f}".rstrip("0").rstrip(".") + "M"
    if v >= 1_000:
        return f"{sign}${v / 1_000:.1f}".rstrip("0").rstrip(".") + "k"
    return f"{sign}${v:.0f}"


def quantity(value):
    return f"{value:,.0f}" if float(value).is_integer() else f"{value:,.2f}"


def price(value):
    return f"{value:,.2f}" if abs(value) >= 10 else f"{value:,.4f}"


def percent(value, places=1):
    return f"{value * 100:.{places}f}%"


def subject(report):
    return f"AlgoGators daily report | {report.portfolio_name} | {report.report_date.isoformat()}"
