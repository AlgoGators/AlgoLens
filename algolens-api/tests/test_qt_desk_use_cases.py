"""QT desk use cases against in-memory fakes."""

from datetime import date, datetime, timedelta, timezone

import pytest

from algolens.application.qt.ports import (
    DeskConflict,
    DeskForbidden,
    DeskGone,
    DeskNotFound,
    DeskNotSeeded,
)
from algolens.application.qt.use_cases import (
    DecideOverride,
    GetCommand,
    GetDeskState,
    ListSymbolChoices,
    LookupApproval,
    PublishDesk,
    RequestOverride,
    SaveDeskEdit,
)
from algolens.domain.qt.desk import DeskRuleError, token_hash

DAY = date(2026, 10, 8)
NOW = datetime(2026, 10, 8, 15, tzinfo=timezone.utc)
QT = {
    "portfolio_id": "QT_CONSERVATIVE_PORTFOLIO",
    "strategy_type": "LIVE_TREND_FOLLOWING",
    "desk_editable": True,
    "asset_class": "futures",
}
MODEL = {**QT, "portfolio_id": "QT_CONSERVATIVE_MODEL_PORTFOLIO", "desk_editable": False}
EQUITY = {**QT, "portfolio_id": "EQ", "strategy_type": "LIVE_EQUITY_MEAN_REVERSION"}


class FakeRepo:
    def __init__(self, day=DAY, proposal=None):
        self.day = day
        self.books = {
            "system": [{"symbol": "ZC.v.0", "quantity": 3, "average_price": 400, "moved_by": None}],
            "qt_proposal": proposal
            if proposal is not None
            else [{"symbol": "ZC.v.0", "quantity": 3, "average_price": 400, "moved_by": None}],
            "qt": [{"symbol": "ZC.v.0", "quantity": 3, "average_price": 400, "moved_by": None}],
        }
        self.rows = []
        self.published = None

    def _insert(self, **row):
        row = {
            "id": len(self.rows) + 1,
            "status": "pending",
            "date": self.day,
            "reason": None,
            "payload": {},
            "parent_id": None,
            "approver_role": None,
            "token_hash": None,
            "token_expires_at": None,
            "result": None,
            "message": None,
            "created_at": NOW,
            "started_at": None,
            "finished_at": None,
            **row,
        }
        self.rows.append(row)
        return row

    def desk_date(self, portfolio_id):
        return self.day

    def book_rows(self, portfolio_id, day, book):
        return self.books[book]

    def save_proposal(self, portfolio_id, day, plan, reason, requested_by):
        current = {r["symbol"]: r["quantity"] for r in self.books["qt_proposal"]}
        changes = plan(current)
        return self._insert(
            portfolio_id=portfolio_id, kind="save", requested_by=requested_by,
            reason=reason, payload={"changes": changes},
        )

    def symbol_choices(self, asset_class):
        return [{"symbol": "6E.v.0", "root": "6E", "name": "EUR/USD", "sector": "FX",
                 "price": 1.1, "price_date": NOW}]

    def get_command(self, command_id):
        return next((r for r in self.rows if r["id"] == command_id), None)

    def commands(self, portfolio_id, day):
        return [r for r in self.rows if r["portfolio_id"] == portfolio_id]

    def insert_command(self, portfolio_id, day, kind, requested_by, reason=None, payload=None):
        return self._insert(portfolio_id=portfolio_id, kind=kind, requested_by=requested_by,
                            reason=reason, payload=payload or {})

    def find_request_by_token_hash(self, h):
        return next((r for r in self.rows if r["token_hash"] == h), None)

    def insert_decision(self, request_id, approved, approver, approver_role, reason):
        if any(r["parent_id"] == request_id for r in self.rows):
            raise DeskConflict("already decided")
        request = self.get_command(request_id)
        return self._insert(portfolio_id=request["portfolio_id"], kind="override_decision",
                            requested_by=approver, reason=reason,
                            payload={"approved": approved}, parent_id=request_id,
                            approver_role=approver_role)

    def publish_state(self, portfolio_id, day):
        return self.published


class FakeAgent:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def _record(self, name, *args):
        self.calls.append((name, *args))
        return "not delivered (UNAVAILABLE)" if self.fail else "COMMAND_STATUS_ACCEPTED"

    def run_desk(self, command):
        return self._record("RunDesk", command["id"])

    def request_override(self, command):
        return self._record("RequestOverride", command["id"])

    def record_decision(self, decision, token):
        return self._record("RecordDecision", decision["id"], token)

    def publish(self, command):
        return self._record("Publish", command["id"])


# --- save (A3) ---------------------------------------------------------------


def test_save_inserts_the_save_row_then_calls_run_desk():
    repo, agent = FakeRepo(), FakeAgent()

    result = SaveDeskEdit(repo, agent).execute(
        QT, [{"symbol": "ZC.v.0", "quantity": 0}], " flatten corn ", "desk@x.com"
    )

    command = result["command"]
    assert command["kind"] == "save" and command["status"] == "pending"
    assert command["reason"] == "flatten corn"
    assert command["payload"] == {"changes": [{"symbol": "ZC.v.0", "from": 3, "to": 0}]}
    assert agent.calls == [("RunDesk", command["id"])]
    assert result["agent"] == "COMMAND_STATUS_ACCEPTED"


def test_save_succeeds_when_the_engine_cannot_be_reached():
    repo, agent = FakeRepo(), FakeAgent(fail=True)

    result = SaveDeskEdit(repo, agent).execute(
        QT, [{"symbol": "ZC.v.0", "quantity": 1}], "r", "desk@x.com"
    )

    assert result["command"]["status"] == "pending"
    assert result["agent"].startswith("not delivered")


def test_saves_are_repeatable():
    repo, agent = FakeRepo(), FakeAgent()
    use_case = SaveDeskEdit(repo, agent)
    use_case.execute(QT, [{"symbol": "ZC.v.0", "quantity": 1}], "a", "d@x.com")
    use_case.execute(QT, [{"symbol": "ZC.v.0", "quantity": 2}], "b", "d@x.com")
    assert [r["kind"] for r in repo.rows] == ["save", "save"]


@pytest.mark.parametrize("entry", [MODEL, EQUITY])
def test_save_is_refused_on_a_portfolio_the_desk_may_not_edit(entry):
    with pytest.raises(DeskForbidden):
        SaveDeskEdit(FakeRepo(), FakeAgent()).execute(
            entry, [{"symbol": "ZC.v.0", "quantity": 1}], "r", "d@x.com"
        )


def test_save_requires_a_reason():
    with pytest.raises(DeskRuleError):
        SaveDeskEdit(FakeRepo(), FakeAgent()).execute(
            QT, [{"symbol": "ZC.v.0", "quantity": 1}], "  ", "d@x.com"
        )


def test_save_before_the_proposal_is_seeded_is_409():
    agent = FakeAgent()
    for repo in (FakeRepo(day=None), FakeRepo(proposal=[])):
        with pytest.raises(DeskNotSeeded):
            SaveDeskEdit(repo, agent).execute(
                QT, [{"symbol": "ZC.v.0", "quantity": 1}], "r", "d@x.com"
            )
    assert agent.calls == []


def test_save_after_publish_is_refused():
    repo = FakeRepo()
    repo.insert_command(QT["portfolio_id"], DAY, "publish", "d@x.com")["status"] = "done"
    with pytest.raises(DeskConflict):
        SaveDeskEdit(repo, FakeAgent()).execute(
            QT, [{"symbol": "ZC.v.0", "quantity": 1}], "r", "d@x.com"
        )


def test_symbol_choices_only_for_editable_books():
    assert ListSymbolChoices(FakeRepo()).execute(QT)[0]["symbol"] == "6E.v.0"
    with pytest.raises(DeskForbidden):
        ListSymbolChoices(FakeRepo()).execute(EQUITY)


# --- state and polling (A4) ----------------------------------------------------


def test_state_shows_books_comparison_and_latest_save():
    repo = FakeRepo()
    repo.books["qt"] = [{"symbol": "ZC.v.0", "quantity": 2, "average_price": 400, "moved_by": "cap"}]
    SaveDeskEdit(repo, FakeAgent()).execute(QT, [{"symbol": "ZC.v.0", "quantity": 5}], "r", "d@x.com")
    repo.rows[-1].update(status="done", message="cap bound", result={"book_source": "desk"})

    state = GetDeskState(repo).execute(QT)

    assert state["date"] == "2026-10-08" and state["seeded"] is True
    assert state["latestSave"]["status"] == "done"
    assert state["latestSave"]["message"] == "cap bound"
    assert "token_hash" not in state["latestSave"]
    assert state["comparison"][0]["moved_by"] == "cap"


def test_get_command_and_unknown_command():
    repo = FakeRepo()
    row = repo.insert_command(QT["portfolio_id"], DAY, "publish", "d@x.com")
    assert GetCommand(repo).execute(row["id"])["kind"] == "publish"
    with pytest.raises(DeskNotFound):
        GetCommand(repo).execute(999)


# --- override (A5) -----------------------------------------------------------


def _emailed_request(repo, requested_by="desk@x.com", expires=NOW + timedelta(hours=48)):
    result = RequestOverride(repo, FakeAgent()).execute(QT, "breach is intended", requested_by)
    row = repo.get_command(result["command"]["id"])
    row.update(token_hash=token_hash("tok"), token_expires_at=expires, status="done")
    return row


def test_override_request_requires_a_reason_and_calls_the_engine():
    repo, agent = FakeRepo(), FakeAgent()
    with pytest.raises(DeskRuleError):
        RequestOverride(repo, agent).execute(QT, "", "d@x.com")
    result = RequestOverride(repo, agent).execute(QT, "because", "d@x.com")
    assert result["command"]["kind"] == "override_request"
    assert agent.calls == [("RequestOverride", result["command"]["id"])]


def test_approval_lookup_by_token_shows_the_three_books():
    repo = FakeRepo()
    request = _emailed_request(repo)

    page = LookupApproval(repo, now=lambda: NOW).execute("tok")

    assert page["request"]["id"] == request["id"]
    assert page["decision"] is None
    assert page["table"][0]["symbol"] == "ZC.v.0"
    assert set(page["books"]) == {"system", "qt_proposal", "qt"}


def test_unknown_or_expired_token():
    repo = FakeRepo()
    _emailed_request(repo, expires=NOW - timedelta(seconds=1))
    with pytest.raises(DeskNotFound):
        LookupApproval(repo, now=lambda: NOW).execute("other")
    with pytest.raises(DeskGone):
        LookupApproval(repo, now=lambda: NOW).execute("tok")
    with pytest.raises(DeskGone):
        DecideOverride(repo, FakeAgent(), now=lambda: NOW).execute("tok", True, "vp@x.com", "vp")


def test_decision_inserts_a_row_and_calls_record_decision():
    repo, agent = FakeRepo(), FakeAgent()
    request = _emailed_request(repo)

    result = DecideOverride(repo, agent, now=lambda: NOW).execute(
        "tok", True, "vp@x.com", "vp", "ok"
    )

    decision = result["command"]
    assert decision["kind"] == "override_decision"
    assert decision["parent_id"] == request["id"]
    assert decision["approver_role"] == "vp"
    assert decision["payload"] == {"approved": True}
    assert agent.calls == [("RecordDecision", decision["id"], "tok")]


def test_decision_refusals():
    repo, agent = FakeRepo(), FakeAgent()
    _emailed_request(repo, requested_by="VP@x.com")
    decide = DecideOverride(repo, agent, now=lambda: NOW)

    with pytest.raises(DeskForbidden):  # not an approver
        decide.execute("tok", True, "someone@x.com", None)
    with pytest.raises(DeskForbidden):  # own request
        decide.execute("tok", True, "vp@x.com", "vp")
    with pytest.raises(DeskRuleError):
        decide.execute("tok", "yes", "p@x.com", "president")
    decide.execute("tok", False, "p@x.com", "president")
    with pytest.raises(DeskConflict):  # already decided
        decide.execute("tok", True, "p@x.com", "president")
    assert [c[0] for c in agent.calls] == ["RecordDecision"]


# --- publish (A6) ------------------------------------------------------------


def test_publish_inserts_a_row_every_day_edited_or_not():
    repo, agent = FakeRepo(), FakeAgent()
    result = PublishDesk(repo, agent).execute(QT, "d@x.com")
    assert result["command"]["kind"] == "publish"
    assert agent.calls == [("Publish", result["command"]["id"])]


def test_publish_refuses_a_second_open_or_done_publish_but_allows_a_retry():
    repo = FakeRepo()
    publish = PublishDesk(repo, FakeAgent())
    first = publish.execute(QT, "d@x.com")["command"]
    with pytest.raises(DeskConflict):
        publish.execute(QT, "d@x.com")
    repo.get_command(first["id"])["status"] = "failed"
    second = publish.execute(QT, "d@x.com")["command"]
    repo.get_command(second["id"])["status"] = "done"
    with pytest.raises(DeskConflict):
        publish.execute(QT, "d@x.com")


def test_publish_state_comes_from_live_run_metadata():
    repo = FakeRepo()
    repo.published = {"published_by": "d@x.com", "published_at": NOW}
    state = GetDeskState(repo).execute(QT)
    assert state["published"] == {"published_by": "d@x.com", "published_at": NOW.isoformat()}
