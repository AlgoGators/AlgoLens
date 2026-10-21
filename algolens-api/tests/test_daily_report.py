"""Daily report: payload rules, rendering, the MIME message, and the worker's use case."""

import copy
import email
from email import policy

import pytest

from algolens.application.reports.ports import Mailer, QueuedReport, ReportQueue
from algolens.application.reports.use_cases import SendQueuedReports
from algolens.domain.reports import daily
from algolens.domain.reports.daily import ReportPayloadError, parse_daily_report
from algolens.infrastructure.reports.mailer import build_message
from algolens.infrastructure.reports.renderer import HtmlReportRenderer
from report_fixture import sample_payload

PNG = b"\x89PNG\r\n\x1a\n"


# --- payload rules ----------------------------------------------------------------------------


def test_sample_payload_parses_and_totals():
    report = parse_daily_report(sample_payload())
    assert report.portfolio_name == "Trend Following"
    assert len(report.positions) == 6
    assert report.total_realized_pnl == pytest.approx(2752.5)
    assert report.total_cost == pytest.approx(8.4)
    assert report.executions[0].side == "BUY"  # normalised


@pytest.mark.parametrize("mutate, message", [
    (lambda p: p.update(schema_version=2), "schema_version"),
    (lambda p: p.update(report_date="21/10/2026"), "report_date"),
    (lambda p: p.pop("portfolio_name"), "portfolio_name"),
    (lambda p: p["positions"][0].update(quantity="2"), "positions[0].quantity"),
    (lambda p: p["notices"][0].update(kind="loud"), "notices[0].kind"),
    (lambda p: p["series"]["equity"][0].update(value=None), "series.equity[0].value"),
])
def test_bad_payloads_are_refused_with_the_field_named(mutate, message):
    payload = copy.deepcopy(sample_payload())
    mutate(payload)
    with pytest.raises(ReportPayloadError, match=message.replace("[", r"\[").replace("]", r"\]")):
        parse_daily_report(payload)


def test_empty_optional_sections_parse():
    report = parse_daily_report({"schema_version": 1, "report_date": "2026-10-21",
                                 "portfolio_id": "P", "portfolio_name": "P"})
    assert report.positions == () and report.equity == ()


def test_number_formats():
    assert daily.money(-1234.6) == "-$1,235"
    assert daily.signed_money(1612.5) == "+$1,612"
    assert daily.signed_money(-0.2) == "$0"
    assert daily.compact_money(2_743_880) == "$2.74M"
    assert daily.compact_money(1_000_000) == "$1M"
    assert daily.compact_money(12_500) == "$12.5k"
    assert daily.price(1.0832) == "1.0832" and daily.price(5412.25) == "5,412.25"


# --- rendering --------------------------------------------------------------------------------


def test_render_has_every_section_and_inline_images():
    out = HtmlReportRenderer().render_daily(parse_daily_report(sample_payload()))
    assert out.subject == "AlgoGators daily report | Trend Following | 2026-10-21"
    for needle in ("Daily Trading Report", "Yesterday was Columbus Day", "Today&#39;s positions",
                   "Executions", "Realized PnL", "Rollover notice", "CLZ6"):
        assert needle in out.html
    assert set(out.images) == {"brandmark", "equity", "daily_pnl", "pnl_by_symbol", "composition"}
    assert all(f"cid:{cid}" in out.html for cid in out.images)
    assert out.images["equity"].startswith(PNG)
    assert "Columbus Day" in out.text


def test_render_escapes_payload_text():
    payload = sample_payload()
    payload["notices"][0]["title"] = "<script>alert(1)</script>"
    out = HtmlReportRenderer().render_daily(parse_daily_report(payload))
    assert "<script>alert" not in out.html and "&lt;script&gt;" in out.html


def test_render_minimal_report_has_no_empty_sections():
    out = HtmlReportRenderer().render_daily(parse_daily_report(
        {"schema_version": 1, "report_date": "2026-10-21", "portfolio_id": "P", "portfolio_name": "P"}))
    for absent in ("Executions", "Performance", "Rollover notice"):
        assert absent not in out.html
    assert set(out.images) == {"brandmark"}


def test_message_is_text_plus_html_with_related_images():
    out = HtmlReportRenderer().render_daily(parse_daily_report(sample_payload()))
    raw = bytes(build_message("reports@algogators.org", ["a@x.com", "b@x.com"], out))
    msg = email.message_from_bytes(raw, policy=policy.default)
    assert msg["To"] == "a@x.com, b@x.com"
    assert msg.get_body(("plain",)) is not None
    assert "cid:equity" in msg.get_body(("html",)).get_content()
    cids = {part["Content-ID"] for part in msg.walk() if part.get_content_maintype() == "image"}
    assert cids == {f"<{c}>" for c in out.images}


# --- worker use case --------------------------------------------------------------------------


class FakeQueue(ReportQueue):
    def __init__(self, items):
        self.items, self.sent, self.failed = list(items), [], {}

    def claim_next(self):
        return self.items.pop(0) if self.items else None

    def mark_sent(self, report_id):
        self.sent.append(report_id)

    def mark_failed(self, report_id, error):
        self.failed[report_id] = error


class FakeMailer(Mailer):
    def __init__(self, fail_for=()):
        self.delivered, self.fail_for = [], set(fail_for)

    def send(self, recipients, email_):
        if recipients[0] in self.fail_for:
            raise ConnectionError("smtp down")
        self.delivered.append((tuple(recipients), email_.subject))


def _item(i, payload=None, recipients=("dom@x.com",), report_type="daily_trading"):
    return QueuedReport(id=i, report_type=report_type, portfolio_id="P", recipients=recipients,
                        payload=payload if payload is not None else sample_payload(), attempts=1)


def test_worker_sends_and_records_each_outcome_without_blocking_the_rest():
    queue = FakeQueue([
        _item(1),
        _item(2, payload={"schema_version": 9}),          # unparseable
        _item(3, recipients=("down@x.com",)),             # mail server refuses
        _item(4, report_type="weekly"),                   # unknown type
        _item(5),
    ])
    mailer = FakeMailer(fail_for={"down@x.com"})
    summary = SendQueuedReports(queue, HtmlReportRenderer(), mailer)()
    assert (summary.sent, summary.failed) == (2, 3)
    assert queue.sent == [1, 5]
    assert "ReportPayloadError" in queue.failed[2]
    assert "ConnectionError" in queue.failed[3]
    assert "unknown report_type" in queue.failed[4]
    assert len(mailer.delivered) == 2


def test_worker_with_an_empty_queue_does_nothing():
    summary = SendQueuedReports(FakeQueue([]), HtmlReportRenderer(), FakeMailer())()
    assert (summary.sent, summary.failed) == (0, 0)
