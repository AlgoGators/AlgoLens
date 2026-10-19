"""QT desk use cases against in-memory fakes."""

from datetime import date, datetime, timedelta, timezone

import pytest

from algolens.application.qt.ports import (
    DeskConflict,
    DeskForbidden,
    DeskGone,
    DeskNotFound,
    DeskNotSeeded,
    DeskRiskUnavailable,
)
import algolens.application.qt.use_cases as use_cases
from algolens.application.qt.use_cases import (
    ApproveDesk,
    DecideOverride,
    GetCommand,
    GetDeskState,
    ListSymbolChoices,
    LookupApproval,
    PublishDesk,
    RequestOverride,
    RescindDesk,
    SendDesk,
    SaveDeskEdit,
)
from algolens.domain.qt import desk as rules
from algolens.domain.qt.desk import DeskRuleError, DeskStaleError, token_hash

DAY = date(2026, 10, 8)
# 08:00 New York (EDT) on DAY: the desk is open until 09:30, approvals until 10:00.
NOW = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)
QT = {
    "portfolio_id": "QT_CONSERVATIVE_PORTFOLIO",
    "strategy_type": "LIVE_TREND_FOLLOWING",
    "desk_editable": True,
    "asset_class": "futures",
}
MODEL = {**QT, "portfolio_id": "QT_CONSERVATIVE_MODEL_PORTFOLIO", "desk_editable": False}
EQUITY = {**QT, "portfolio_id": "EQ", "strategy_type": "LIVE_EQUITY_MEAN_REVERSION"}


@pytest.fixture(autouse=True)
def _desk_clock(monkeypatch):
    """The use cases' default clock is NOW (before the 09:30 cutoff) unless a
    test passes its own."""
    monkeypatch.setattr(use_cases, "_utcnow", lambda: NOW)


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
        self.now = NOW
        self.tracks_sends = True

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

    # The Postgres repository's checks, made under its day lock.

    def _is_published(self, portfolio_id):
        return bool(self.published and self.published.get("published_at"))

    def _guard(self, portfolio_id, refuse_open_publish=True):
        if self._is_published(portfolio_id):
            raise DeskConflict("already published")
        if refuse_open_publish and any(
            r["kind"] == "publish" and r["status"] in ("pending", "running") for r in self.rows
        ):
            raise DeskConflict("publish open")

    def proposal_rows(self, portfolio_id, day):
        return [
            {"strategy_name": "TF", "symbol": r["symbol"], "quantity": r["quantity"]}
            for r in self.books["qt_proposal"]
        ]

    def _sha(self):
        return rules.snapshot_sha256(rules.proposal_snapshot(self.proposal_rows(None, None)))

    def save_proposal(self, portfolio_id, day, plan, reason, requested_by):
        self._guard(portfolio_id)
        current = {r["symbol"]: r["quantity"] for r in self.books["qt_proposal"]}
        changes = plan(current)
        for change in changes:
            row = next((r for r in self.books["qt_proposal"] if r["symbol"] == change["symbol"]), None)
            if row is None:
                self.books["qt_proposal"].append(
                    {"symbol": change["symbol"], "quantity": change["to"], "average_price": 1,
                     "moved_by": None})
            else:
                row["quantity"] = change["to"]
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
        """Test helper: a raw row, no checks."""
        return self._insert(portfolio_id=portfolio_id, kind=kind, requested_by=requested_by,
                            reason=reason, payload=payload or {})

    def insert_publish(self, portfolio_id, day, requested_by, payload=None):
        self._guard(portfolio_id)
        return self._insert(portfolio_id=portfolio_id, kind="publish", requested_by=requested_by,
                            payload=dict(payload or {}))

    def approve_proposal(self, portfolio_id, day, plan, reason, requested_by, email=True):
        save = self.save_proposal(portfolio_id, day, plan, reason, requested_by)
        payload = {"flow": "auto", "after": save["id"]}
        if not email:
            payload["email"] = False
        publish = self._insert(portfolio_id=portfolio_id, kind="publish",
                               requested_by=requested_by, payload=payload)
        return save, publish

    def insert_send(self, portfolio_id, day, requested_by):
        if not self._is_published(portfolio_id):
            raise DeskConflict("not approved")
        if self.published.get("sent_at") is not None:
            raise DeskConflict("already been e-mailed")
        return self._insert(portfolio_id=portfolio_id, kind="publish",
                            requested_by=requested_by, payload={"flow": "send"})

    def decide_override(self, request_id, approved, approver, approver_role, reason):
        decision = self.insert_decision(request_id, approved, approver, approver_role, reason)
        if not approved:
            return decision, None
        request = self.get_command(request_id)
        if any(r["kind"] == "publish" and r["status"] in rules.OPEN_STATUSES
               and r["portfolio_id"] == request["portfolio_id"] for r in self.rows):
            raise DeskConflict("a publish is open")
        publish = self._insert(portfolio_id=request["portfolio_id"], kind="publish",
                               requested_by=request["requested_by"],
                               payload={"flow": "override_b", "after": decision["id"]})
        return decision, publish

    def insert_rescind(self, portfolio_id, day, requested_by, is_approver=False):
        if not self._is_published(portfolio_id):
            raise DeskConflict("not approved")
        if self.published.get("publish_source") != "desk":
            raise DeskConflict("not approved by the desk")
        why = rules.rescind_refusal(rules.approving_flow(self.rows), day.isoformat(), is_approver)
        if why:
            raise DeskConflict(why)
        if self.published.get("sent_at") is not None:
            raise DeskConflict("already e-mailed")
        if any(
            r["kind"] in ("publish", "rescind") and r["status"] in ("pending", "running")
            for r in self.rows
        ):
            raise DeskConflict("publish or rescind open")
        return self._insert(portfolio_id=portfolio_id, kind="rescind", requested_by=requested_by)

    def insert_override_request(self, portfolio_id, day, requested_by, reason):
        self._guard(portfolio_id)
        payload = rules.override_payload(self.proposal_rows(portfolio_id, day))
        if rules.open_override_request(self.rows, self.now, payload["proposal_sha256"]):
            raise DeskConflict("a request is open")
        return self._insert(portfolio_id=portfolio_id, kind="override_request",
                            requested_by=requested_by, reason=reason, payload=payload)

    def find_request_by_token_hash(self, h):
        return next((r for r in self.rows if r["token_hash"] == h), None)

    def insert_decision(self, request_id, approved, approver, approver_role, reason):
        if any(r["parent_id"] == request_id and r["status"] in rules.DECIDING_STATUSES
               for r in self.rows):
            raise DeskConflict("already decided")
        request = self.get_command(request_id)
        if request["status"] != "done":
            raise DeskConflict("not e-mailed")
        self._guard(request["portfolio_id"], refuse_open_publish=False)
        if approved and not rules.request_matches(request, self._sha()):
            raise DeskConflict("the proposal changed after the override was requested")
        return self._insert(portfolio_id=request["portfolio_id"], kind="override_decision",
                            requested_by=approver, reason=reason,
                            payload={"approved": approved}, parent_id=request_id,
                            approver_role=approver_role)

    def publish_state(self, portfolio_id, day):
        return self.published

    def send_tracking(self):
        return self.tracks_sends


def risk_report(state="model", audit_id=0, within_limits=True, approved_override=False,
                breaches=(), blockers=()):
    """A GetDeskRisk report as DeskClient.get_desk_risk returns it."""
    return {
        "state": state,
        "auditId": audit_id,
        "withinLimits": within_limits,
        "approvedOverride": approved_override,
        "breaches": [{"term": t, "detail": f"{t} bound"} for t in breaches],
        # Decision 5's gate as the engine decides it (desk.proto 1.6.0).
        "blocksPublish": bool(blockers),
        "blockers": [{"term": t, "detail": f"{t} over its cap"} for t in blockers],
        "m": 1.0,
        "bindingTerm": "none",
        "overLimitAfterRounding": "",
        "overLimitByHold": "",
        "refused": False,
        "symbols": [],
        "grossLeverage": None,
        "netLeverage": None,
        "marginCushion": None,
        "equityToMargin": None,
        "limits": [],
        "checks": [],
    }


class FakeAgent:
    """The commands record their calls; get_desk_risk returns `risk` (the
    model's book by default) or raises DeskRiskUnavailable(`risk_down`)."""

    def __init__(self, fail=False, risk=None, risk_down=None):
        self.calls = []
        self.fail = fail
        self.risk = risk if risk is not None else risk_report()
        self.risk_down = risk_down
        self.risk_calls = []
        self.status = {"state": "succeeded", "startedAt": None, "finishedAt": None, "message": ""}
        self.status_down = None
        self.status_calls = []

    def get_run_status(self, portfolio_id, day):
        self.status_calls.append((portfolio_id, day))
        if self.status_down:
            raise DeskRiskUnavailable(self.status_down)
        return self.status

    def get_desk_risk(self, portfolio_id, day):
        self.risk_calls.append((portfolio_id, day))
        if self.risk_down:
            raise DeskRiskUnavailable(self.risk_down)
        return self.risk

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

    def rescind(self, command):
        return self._record("Rescind", command["id"])


# --- save (A3) ---------------------------------------------------------------


def test_save_inserts_the_save_row_then_calls_run_desk():
    repo, agent = FakeRepo(), FakeAgent()

    result = SaveDeskEdit(repo, agent).execute(
        QT, [{"symbol": "ZC.v.0", "quantity": 0, "expected": 3}], " flatten corn ", "desk@x.com"
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
        QT, [{"symbol": "ZC.v.0", "quantity": 1, "expected": 3}], "r", "desk@x.com"
    )

    assert result["command"]["status"] == "pending"
    assert result["agent"].startswith("not delivered")


def test_saves_are_repeatable():
    repo, agent = FakeRepo(), FakeAgent()
    use_case = SaveDeskEdit(repo, agent)
    use_case.execute(QT, [{"symbol": "ZC.v.0", "quantity": 1, "expected": 3}], "a", "d@x.com")
    use_case.execute(QT, [{"symbol": "ZC.v.0", "quantity": 2, "expected": 1}], "b", "d@x.com")
    assert [r["kind"] for r in repo.rows] == ["save", "save"]


@pytest.mark.parametrize("entry", [MODEL, EQUITY])
def test_save_is_refused_on_a_portfolio_the_desk_may_not_edit(entry):
    with pytest.raises(DeskForbidden):
        SaveDeskEdit(FakeRepo(), FakeAgent()).execute(
            entry, [{"symbol": "ZC.v.0", "quantity": 1, "expected": 3}], "r", "d@x.com"
        )


def test_save_requires_a_reason():
    with pytest.raises(DeskRuleError):
        SaveDeskEdit(FakeRepo(), FakeAgent()).execute(
            QT, [{"symbol": "ZC.v.0", "quantity": 1, "expected": 3}], "  ", "d@x.com"
        )


def test_save_before_the_proposal_is_seeded_is_409():
    agent = FakeAgent()
    for repo in (FakeRepo(day=None), FakeRepo(proposal=[])):
        with pytest.raises(DeskNotSeeded):
            SaveDeskEdit(repo, agent).execute(
                QT, [{"symbol": "ZC.v.0", "quantity": 1, "expected": 3}], "r", "d@x.com"
            )
    assert agent.calls == []


def test_save_after_publish_is_refused():
    repo = FakeRepo()
    repo.insert_command(QT["portfolio_id"], DAY, "publish", "d@x.com")["status"] = "done"
    repo.published = {"published_by": "d@x.com", "published_at": NOW}
    with pytest.raises(DeskConflict):
        SaveDeskEdit(repo, FakeAgent()).execute(
            QT, [{"symbol": "ZC.v.0", "quantity": 1, "expected": 3}], "r", "d@x.com"
        )


def test_a_rescinded_approval_reopens_the_day():
    # The approval's row stays done; live_run_metadata.published_at is cleared again.
    repo = FakeRepo()
    repo.insert_command(QT["portfolio_id"], DAY, "publish", "d@x.com")["status"] = "done"
    repo.published = None
    state = GetDeskState(repo, FakeAgent()).execute(QT)
    assert state["published"] is None
    assert state["locked"] is None
    save = SaveDeskEdit(repo, FakeAgent()).execute(
        QT, [{"symbol": "ZC.v.0", "quantity": 1, "expected": 3}], "r", "d@x.com"
    )["command"]
    repo.get_command(save["id"])["status"] = "done"
    agent = FakeAgent(risk=risk_report("desk", audit_id=save["id"]))
    assert PublishDesk(repo, agent).execute(QT, "d@x.com")["command"]["kind"] == "publish"


def test_symbol_choices_only_for_editable_books():
    assert ListSymbolChoices(FakeRepo()).execute(QT)[0]["symbol"] == "6E.v.0"
    with pytest.raises(DeskForbidden):
        ListSymbolChoices(FakeRepo()).execute(EQUITY)


# --- state and polling (A4) ----------------------------------------------------


def test_state_shows_books_comparison_and_latest_save():
    repo = FakeRepo()
    repo.books["qt"] = [{"symbol": "ZC.v.0", "quantity": 2, "average_price": 400, "moved_by": "cap"}]
    SaveDeskEdit(repo, FakeAgent()).execute(QT, [{"symbol": "ZC.v.0", "quantity": 5, "expected": 3}], "r", "d@x.com")
    repo.rows[-1].update(status="done", message="cap bound", result={"book_source": "desk"})

    state = GetDeskState(repo, FakeAgent()).execute(QT)

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

    page = LookupApproval(repo, FakeAgent(), now=lambda: NOW).execute("tok")

    assert page["request"]["id"] == request["id"]
    assert page["decision"] is None
    assert page["table"][0]["symbol"] == "ZC.v.0"
    assert set(page["books"]) == {"system", "qt_proposal", "qt"}


def test_unknown_or_expired_token():
    repo = FakeRepo()
    _emailed_request(repo, expires=NOW - timedelta(seconds=1))
    with pytest.raises(DeskNotFound):
        LookupApproval(repo, FakeAgent(), now=lambda: NOW).execute("other")
    with pytest.raises(DeskGone):
        LookupApproval(repo, FakeAgent(), now=lambda: NOW).execute("tok")
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
    # C10: the approval also queues the publish of B, requested by the QT who asked.
    publish = result["publish"]
    assert publish["kind"] == "publish" and publish["requested_by"] == request["requested_by"]
    assert publish["payload"] == {"flow": "override_b", "after": decision["id"]}
    assert agent.calls == [("RecordDecision", decision["id"], "tok"), ("Publish", publish["id"])]


def test_a_rejection_publishes_nothing():
    repo, agent = FakeRepo(), FakeAgent()
    _emailed_request(repo)
    result = DecideOverride(repo, agent, now=lambda: NOW).execute("tok", False, "vp@x.com", "vp")
    assert "publish" not in result
    assert [c[0] for c in agent.calls] == ["RecordDecision"]


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
    repo.published = {"published_by": "d@x.com", "published_at": NOW}
    with pytest.raises(DeskConflict):
        publish.execute(QT, "d@x.com")


def test_publish_state_comes_from_live_run_metadata():
    repo = FakeRepo()
    repo.published = {"published_by": "d@x.com", "published_at": NOW}
    state = GetDeskState(repo, FakeAgent()).execute(QT)
    assert state["published"] == {
        "published_by": "d@x.com",
        "published_at": NOW.isoformat(),
        "publish_source": "desk",
        "sent_at": None,
        "flow": None,
        "email": None,
    }


# --- hardening (2026-10-09 spec) ---------------------------------------------


def test_a_published_day_refuses_save_override_and_publish():
    repo = FakeRepo()
    repo.published = {"published_by": "system:non-trading-day", "published_at": NOW}
    with pytest.raises(DeskConflict):
        SaveDeskEdit(repo, FakeAgent()).execute(
            QT, [{"symbol": "ZC.v.0", "quantity": 1, "expected": 3}], "r", "d@x.com")
    with pytest.raises(DeskConflict):
        RequestOverride(repo, FakeAgent()).execute(QT, "r", "d@x.com")
    with pytest.raises(DeskConflict):
        PublishDesk(repo, FakeAgent()).execute(QT, "d@x.com")
    assert repo.rows == []
    state = GetDeskState(repo, FakeAgent(), now=lambda: NOW).execute(QT)
    assert state["locked"] == "published"


def test_the_override_request_carries_the_snapshot():
    repo = FakeRepo()
    command = RequestOverride(repo, FakeAgent()).execute(QT, "r", "d@x.com")["command"]
    assert command["payload"]["proposal"] == [
        {"strategy_name": "TF", "symbol": "ZC.v.0", "quantity": 3}]
    assert len(command["payload"]["proposal_sha256"]) == 64


def test_an_approval_of_a_changed_proposal_is_refused():
    repo = FakeRepo()
    _emailed_request(repo)
    SaveDeskEdit(repo, FakeAgent()).execute(
        QT, [{"symbol": "ZC.v.0", "quantity": 1, "expected": 3}], "r", "d@x.com")
    page = LookupApproval(repo, FakeAgent(), now=lambda: NOW).execute("tok")
    assert page["snapshotMatches"] is False and page["snapshot"][0]["quantity"] == 3
    with pytest.raises(DeskConflict):
        DecideOverride(repo, FakeAgent(), now=lambda: NOW).execute("tok", True, "p@x.com", "president")


def test_state_shows_the_open_request_and_the_publishing_lock():
    repo = FakeRepo()
    request = _emailed_request(repo)
    state = GetDeskState(repo, FakeAgent(), now=lambda: NOW).execute(QT)
    assert state["openOverrideRequestId"] == request["id"] and state["locked"] is None
    PublishDesk(repo, FakeAgent()).execute(QT, "d@x.com")
    assert GetDeskState(repo, FakeAgent(), now=lambda: NOW).execute(QT)["locked"] == "publishing"


def test_a_stale_save_names_the_symbols():
    repo = FakeRepo()
    with pytest.raises(DeskStaleError) as stale:
        SaveDeskEdit(repo, FakeAgent()).execute(
            QT, [{"symbol": "ZC.v.0", "quantity": 1, "expected": 2}], "r", "d@x.com")
    assert stale.value.symbols == ["ZC.v.0"] and repo.rows == []


# --- the daily approval cutoff (2026-10-09: approve by 09:30, fallback at 10:00) --


def _ny(day, hour, minute=0, second=0):
    """An instant given as New York wall-clock time on `day`."""
    from zoneinfo import ZoneInfo

    return datetime(day.year, day.month, day.day, hour, minute, second,
                    tzinfo=ZoneInfo("America/New_York"))


def _approve_at(now, day=DAY):
    repo, agent = FakeRepo(day=day), FakeAgent()
    return repo, agent, PublishDesk(repo, agent, now=lambda: now)


@pytest.mark.parametrize("hour, minute", [(7, 0), (9, 29), (9, 30), (9, 59)])
def test_approve_is_accepted_until_10_new_york(hour, minute):
    repo, agent, approve = _approve_at(_ny(DAY, hour, minute))
    command = approve.execute(QT, "d@x.com")["command"]
    assert command["kind"] == "publish" and agent.calls == [("Publish", command["id"])]


@pytest.mark.parametrize("hour, minute", [(10, 0), (10, 7), (23, 59)])
def test_approve_from_10_new_york_is_refused_without_a_row(hour, minute):
    repo, agent, approve = _approve_at(_ny(DAY, hour, minute))
    with pytest.raises(DeskConflict, match="closed at 10:00 New York"):
        approve.execute(QT, "d@x.com")
    assert repo.rows == [] and agent.calls == []


def test_approve_after_10_on_a_published_day_says_published():
    repo, agent, approve = _approve_at(_ny(DAY, 10, 7))
    repo.published = {"published_by": "system:fallback-10am", "published_at": _ny(DAY, 10, 1),
                      "publish_source": "fallback", "sent_at": _ny(DAY, 10, 1)}
    with pytest.raises(DeskConflict, match="already published .by system:fallback-10am"):
        approve.execute(QT, "d@x.com")


def test_a_past_book_date_is_closed_at_any_hour():
    # The desk still shows yesterday's book (today's model run is not in yet).
    repo, agent, approve = _approve_at(_ny(DAY + timedelta(days=1), 7, 0))
    with pytest.raises(DeskConflict, match="closed"):
        approve.execute(QT, "d@x.com")


@pytest.mark.parametrize(
    "day, utc_hour, utc_minute, accepted",
    [
        # 2026-11-01: clocks go back at 02:00, so 10:00 New York is 15:00 UTC (EST).
        (date(2026, 11, 1), 14, 30, True),   # 09:30 EST (10:30 at EDT's offset)
        (date(2026, 11, 1), 14, 59, True),
        (date(2026, 11, 1), 15, 0, False),
        # 2026-03-08: clocks go forward at 02:00, so 10:00 New York is 14:00 UTC (EDT).
        (date(2026, 3, 8), 13, 59, True),
        (date(2026, 3, 8), 14, 0, False),   # 10:00 EDT (09:00 at EST's offset)
    ],
)
def test_the_cutoff_follows_new_york_across_dst(day, utc_hour, utc_minute, accepted):
    now = datetime(day.year, day.month, day.day, utc_hour, utc_minute, tzinfo=timezone.utc)
    repo, agent, approve = _approve_at(now, day=day)
    if accepted:
        approve.execute(QT, "d@x.com")
        assert len(repo.rows) == 1
    else:
        with pytest.raises(DeskConflict):
            approve.execute(QT, "d@x.com")
        assert repo.rows == []


@pytest.mark.parametrize("day", [date(2026, 10, 10), date(2026, 10, 11)])  # Sat, Sun
def test_weekends_follow_the_same_cutoff(day):
    _repo, _agent, approve = _approve_at(_ny(day, 9, 45), day=day)
    approve.execute(QT, "d@x.com")
    _repo, _agent, approve = _approve_at(_ny(day, 10, 0), day=day)
    with pytest.raises(DeskConflict):
        approve.execute(QT, "d@x.com")


def test_save_override_request_and_decision_are_closed_from_10_new_york():
    repo = FakeRepo()
    _emailed_request(repo, expires=_ny(DAY, 23))
    late = lambda: _ny(DAY, 10, 0)  # noqa: E731
    with pytest.raises(DeskConflict, match="Editing of the 2026-10-08 book closed"):
        SaveDeskEdit(repo, FakeAgent(), now=late).execute(
            QT, [{"symbol": "ZC.v.0", "quantity": 1, "expected": 3}], "r", "d@x.com")
    with pytest.raises(DeskConflict, match="closed at 10:00"):
        RequestOverride(repo, FakeAgent(), now=late).execute(QT, "r", "d@x.com")
    with pytest.raises(DeskConflict, match="closed at 10:00"):
        DecideOverride(repo, FakeAgent(), now=late).execute("tok", True, "p@x.com", "president")
    assert [r["kind"] for r in repo.rows] == ["override_request"]
    # Until 10:00 they are open, as before.
    early = lambda: _ny(DAY, 9, 59)  # noqa: E731
    SaveDeskEdit(repo, FakeAgent(), now=early).execute(
        QT, [{"symbol": "ZC.v.0", "quantity": 1, "expected": 3}], "r", "d@x.com")
    DecideOverride(repo, FakeAgent(), now=early).execute("tok", False, "p@x.com", "president")
    assert [r["kind"] for r in repo.rows] == ["override_request", "save", "override_decision"]


def test_desk_state_carries_the_server_time_and_new_york_deadlines():
    state = GetDeskState(FakeRepo(), FakeAgent(), now=lambda: _ny(DAY, 9, 0)).execute(QT)
    assert state["serverTime"] == "2026-10-08T13:00:00+00:00"
    assert state["deadlines"] == {
        "timezone": "America/New_York",
        "today": "2026-10-08",
        "bookDate": "2026-10-08",
        "approveBy": "2026-10-08T09:30:00-04:00",
        "fallbackAt": "2026-10-08T10:00:00-04:00",
        "todayApproveBy": "2026-10-08T09:30:00-04:00",
        "todayFallbackAt": "2026-10-08T10:00:00-04:00",
        "approvalClosed": False,
    }
    assert state["sendTracked"] is True


def test_desk_state_deadlines_on_a_dst_day_a_weekend_and_before_the_first_book():
    nov1 = GetDeskState(FakeRepo(day=date(2026, 11, 1)), FakeAgent(),
                        now=lambda: _ny(date(2026, 11, 1), 10, 0)).execute(QT)
    assert nov1["deadlines"]["approveBy"] == "2026-11-01T09:30:00-05:00"
    assert nov1["deadlines"]["approvalClosed"] is True
    # No book yet (a Saturday): the deadlines are today's.
    none = GetDeskState(FakeRepo(day=None), FakeAgent(), now=lambda: _ny(date(2026, 10, 10), 6, 0)).execute(QT)
    assert none["deadlines"]["bookDate"] == "2026-10-10"
    assert none["deadlines"]["approveBy"] == "2026-10-10T09:30:00-04:00"
    assert none["deadlines"]["approvalClosed"] is False
    # The desk still shows yesterday's book: today's deadlines come separately.
    old = GetDeskState(FakeRepo(), FakeAgent(), now=lambda: _ny(DAY + timedelta(days=1), 6, 0)).execute(QT)
    assert old["deadlines"]["bookDate"] == "2026-10-08"
    assert old["deadlines"]["today"] == "2026-10-09"
    assert old["deadlines"]["todayApproveBy"] == "2026-10-09T09:30:00-04:00"
    assert old["deadlines"]["approvalClosed"] is True


def test_desk_state_reads_publish_source_and_sent_at():
    repo = FakeRepo()
    repo.published = {"published_by": "d@x.com", "published_at": _ny(DAY, 9, 0),
                      "publish_source": "desk", "sent_at": _ny(DAY, 9, 30, 4)}
    published = GetDeskState(repo, FakeAgent(), now=lambda: _ny(DAY, 9, 31)).execute(QT)["published"]
    assert published["publish_source"] == "desk"
    assert published["sent_at"] == "2026-10-08T09:30:04-04:00"


@pytest.mark.parametrize(
    "published_by, source",
    [
        ("system:fallback-10am", "fallback"),
        ("system:fallback-catchup", "fallback"),
        ("system:model-only", "model-only"),
        ("system:non-trading-day", "system"),
        ("desk@x.com", "desk"),
    ],
)
def test_without_the_026_columns_the_source_is_read_from_published_by(published_by, source):
    repo = FakeRepo()
    repo.tracks_sends = False
    repo.published = {"published_by": published_by, "published_at": _ny(DAY, 10, 1)}
    state = GetDeskState(repo, FakeAgent(), now=lambda: _ny(DAY, 10, 5)).execute(QT)
    assert state["published"]["publish_source"] == source
    assert state["published"]["sent_at"] is None
    assert state["sendTracked"] is False


def test_the_approval_page_shows_the_deadline():
    repo = FakeRepo()
    _emailed_request(repo)
    page = LookupApproval(repo, FakeAgent(), now=lambda: _ny(DAY, 9, 0)).execute("tok")
    assert page["deadlines"]["approveBy"] == "2026-10-08T09:30:00-04:00"
    assert page["deadlines"]["fallbackAt"] == "2026-10-08T10:00:00-04:00"
    assert page["serverTime"] == "2026-10-08T13:00:00+00:00"


# --- rescind (C8: the desk takes back its approval before the 09:30 send) -------


def _approved(day=DAY, sent_at=None, source="desk", flow=None):
    """A day the desk approved: its publish row done (with the C10 flow that approved it),
    live_run_metadata published."""
    repo, agent = FakeRepo(day=day), FakeAgent()
    row = repo.insert_command(QT["portfolio_id"], day, "publish", "d@x.com",
                              payload={"flow": flow} if flow else None)
    row.update(status="done", result={"published": True, "published_at": "2026-10-08T12:00:00Z"})
    repo.published = {"published_by": "d@x.com", "published_at": _ny(day, 8, 0),
                      "publish_source": source, "sent_at": sent_at}
    return repo, agent


def test_rescind_inserts_a_row_then_calls_the_engine():
    repo, agent = _approved()
    result = RescindDesk(repo, agent, now=lambda: _ny(DAY, 9, 0)).execute(QT, "d@x.com")
    command = result["command"]
    assert command["kind"] == "rescind" and command["status"] == "pending"
    assert command["requested_by"] == "d@x.com"
    assert agent.calls == [("Rescind", command["id"])]
    assert result["agent"] == "COMMAND_STATUS_ACCEPTED"


def test_rescind_succeeds_when_the_engine_cannot_be_reached():
    repo, _agent = _approved()
    result = RescindDesk(repo, FakeAgent(fail=True), now=lambda: _ny(DAY, 9, 0)).execute(
        QT, "d@x.com")
    assert result["command"]["status"] == "pending"
    assert result["agent"].startswith("not delivered")


@pytest.mark.parametrize("hour, minute", [(9, 30), (9, 45), (10, 0), (23, 59)])
def test_rescind_from_0930_new_york_is_refused_without_a_row(hour, minute):
    repo, agent = _approved()
    with pytest.raises(DeskConflict, match="can no longer be taken back"):
        RescindDesk(repo, agent, now=lambda: _ny(DAY, hour, minute)).execute(QT, "d@x.com")
    assert [r["kind"] for r in repo.rows] == ["publish"] and agent.calls == []


def test_rescind_at_0929_is_accepted_and_a_past_book_date_is_closed():
    repo, agent = _approved()
    RescindDesk(repo, agent, now=lambda: _ny(DAY, 9, 29, 59)).execute(QT, "d@x.com")
    assert [r["kind"] for r in repo.rows] == ["publish", "rescind"]
    repo, agent = _approved()
    with pytest.raises(DeskConflict):
        RescindDesk(repo, agent, now=lambda: _ny(DAY + timedelta(days=1), 7, 0)).execute(
            QT, "d@x.com")


def test_rescind_follows_new_york_across_dst():
    nov1 = date(2026, 11, 1)  # 09:30 EST is 14:30 UTC
    repo, agent = _approved(day=nov1)
    before = datetime(2026, 11, 1, 14, 29, tzinfo=timezone.utc)
    RescindDesk(repo, agent, now=lambda: before).execute(QT, "d@x.com")
    repo, agent = _approved(day=nov1)
    at = datetime(2026, 11, 1, 14, 30, tzinfo=timezone.utc)
    with pytest.raises(DeskConflict):
        RescindDesk(repo, agent, now=lambda: at).execute(QT, "d@x.com")


def test_rescind_refusals_from_the_repository():
    early = lambda: _ny(DAY, 9, 0)  # noqa: E731
    with pytest.raises(DeskConflict, match="not approved"):  # nothing to take back
        RescindDesk(FakeRepo(), FakeAgent(), now=early).execute(QT, "d@x.com")
    repo, agent = _approved(source="fallback")
    with pytest.raises(DeskConflict, match="not approved by the desk"):
        RescindDesk(repo, agent, now=early).execute(QT, "d@x.com")
    repo, agent = _approved(sent_at=_ny(DAY, 8, 30))
    with pytest.raises(DeskConflict, match="e-mailed"):
        RescindDesk(repo, agent, now=early).execute(QT, "d@x.com")
    repo, agent = _approved()
    rescind = RescindDesk(repo, agent, now=early)
    rescind.execute(QT, "d@x.com")
    with pytest.raises(DeskConflict, match="open"):  # one open rescind a day
        rescind.execute(QT, "d@x.com")
    assert [c[0] for c in agent.calls] == ["Rescind"]


@pytest.mark.parametrize("flow", [None, "auto", "accept_c"])
def test_anyone_on_qt_can_rescind_a_desk_approval(flow):
    # Dom 2026-10-16: not only the approver (the route lets only the QT screen in).
    repo, agent = _approved(flow=flow)  # approved by d@x.com
    RescindDesk(repo, agent, now=lambda: _ny(DAY, 9, 0)).execute(QT, "someone@x.com")
    assert [c[0] for c in agent.calls] == ["Rescind"]


def test_only_the_vp_or_president_can_rescind_an_override_day():
    early = lambda: _ny(DAY, 9, 0)  # noqa: E731
    repo, agent = _approved(flow="override_b")
    for who in ("d@x.com", "someone@x.com"):
        with pytest.raises(DeskConflict, match="only the VP or the President can take it back"):
            RescindDesk(repo, agent, now=early).execute(QT, who)
    assert agent.calls == []
    RescindDesk(repo, agent, now=early).execute(QT, "vp@x.com", is_approver=True)
    assert [c[0] for c in agent.calls] == ["Rescind"]


def test_desk_state_says_which_flow_approved_the_day_and_whether_the_viewer_approves():
    repo, _agent = _approved(flow="override_b")
    now = lambda: _ny(DAY, 9, 0)  # noqa: E731
    state = GetDeskState(repo, FakeAgent(), now=now).execute(QT)
    assert state["published"]["flow"] == "override_b" and state["viewerIsApprover"] is False
    state = GetDeskState(repo, FakeAgent(), now=now).execute(QT, viewer_is_approver=True)
    assert state["viewerIsApprover"] is True


@pytest.mark.parametrize("entry", [MODEL, EQUITY])
def test_rescind_is_refused_on_a_portfolio_the_desk_may_not_edit(entry):
    repo, agent = _approved()
    with pytest.raises(DeskForbidden):
        RescindDesk(repo, agent, now=lambda: _ny(DAY, 9, 0)).execute(entry, "d@x.com")
    assert agent.calls == []


def test_rescind_before_the_proposal_is_seeded_is_409():
    with pytest.raises(DeskNotSeeded):
        RescindDesk(FakeRepo(day=None), FakeAgent(), now=lambda: _ny(DAY, 9, 0)).execute(
            QT, "d@x.com")


def test_desk_state_carries_the_latest_rescind_and_a_done_rescind_reopens_the_day():
    repo, agent = _approved()
    now = lambda: _ny(DAY, 9, 0)  # noqa: E731
    assert GetDeskState(repo, FakeAgent(), now=now).execute(QT)["rescind"] is None
    command = RescindDesk(repo, agent, now=now).execute(QT, "d@x.com")["command"]
    state = GetDeskState(repo, FakeAgent(), now=now).execute(QT)
    assert state["rescind"]["id"] == command["id"] and state["rescind"]["status"] == "pending"
    assert state["locked"] == "published"
    # The engine clears published_at and finishes the row done.
    repo.get_command(command["id"]).update(
        status="done", message="approval of 2026-10-08 rescinded",
        result={"rescinded": {"published_by": "d@x.com"}})
    repo.published = None
    state = GetDeskState(repo, FakeAgent(), now=now).execute(QT)
    assert state["rescind"]["status"] == "done" and state["locked"] is None
    assert state["published"] is None
    second = PublishDesk(repo, FakeAgent(), now=now).execute(QT, "d@x.com")["command"]
    assert second["kind"] == "publish"


# --- the risk check (C9) ---------------------------------------------------------


def _saved(repo, status="done"):
    """A desk save of the day, finished with `status`."""
    current = next(r["quantity"] for r in repo.books["qt_proposal"] if r["symbol"] == "ZC.v.0")
    save = SaveDeskEdit(repo, FakeAgent()).execute(
        QT, [{"symbol": "ZC.v.0", "quantity": current + 1, "expected": current}], "r", "d@x.com"
    )["command"]
    repo.get_command(save["id"])["status"] = status
    return save["id"]


def test_desk_state_carries_the_risk_report():
    repo = FakeRepo()
    agent = FakeAgent(risk=risk_report("desk", audit_id=4, within_limits=False, breaches=["L_g"]))
    state = GetDeskState(repo, agent).execute(QT)
    assert state["risk"]["state"] == "desk" and state["risk"]["withinLimits"] is False
    assert agent.risk_calls == [("QT_CONSERVATIVE_PORTFOLIO", DAY)]


def test_desk_state_says_when_the_risk_check_is_unavailable():
    state = GetDeskState(FakeRepo(), FakeAgent(risk_down="UNAVAILABLE")).execute(QT)
    assert state["risk"] == {"unavailable": "UNAVAILABLE"}
    # The rest of the state is unchanged.
    assert state["seeded"] is True and state["locked"] is None


def test_desk_state_has_no_risk_before_the_first_book():
    agent = FakeAgent()
    state = GetDeskState(FakeRepo(day=None), agent).execute(QT)
    assert state["risk"] is None and agent.risk_calls == []


def test_approve_is_refused_while_the_engine_blocks_the_book():
    repo = FakeRepo()
    save_id = _saved(repo)
    agent = FakeAgent(risk=risk_report("desk", audit_id=save_id, within_limits=False,
                                       breaches=["L_g"], blockers=["L_g", "CAP"]))
    with pytest.raises(DeskConflict) as exc:
        PublishDesk(repo, agent).execute(QT, "d@x.com")
    assert str(exc.value) == (
        "The 2026-10-08 positions are over a cap (L_g over its cap; CAP over its cap): save "
        "within the caps or ask the VP or President to approve your positions"
    )
    assert [r["kind"] for r in repo.rows] == ["save"]
    assert agent.calls == []


def test_a_breach_the_engine_does_not_block_on_is_approvable():
    # Decision 5: a bound limit, R and the trim are reported; only the gate blocks.
    repo = FakeRepo()
    save_id = _saved(repo)
    agent = FakeAgent(risk=risk_report("desk", audit_id=save_id, within_limits=False,
                                       breaches=["R", "cap"]))
    assert PublishDesk(repo, agent).execute(QT, "d@x.com")["command"]["kind"] == "publish"


def test_the_margin_cap_is_never_overridable():
    repo = FakeRepo()
    _saved(repo)
    agent = FakeAgent(risk=risk_report("override", audit_id=99, within_limits=False,
                                       approved_override=True, blockers=["MARGIN"]))
    with pytest.raises(DeskConflict, match="the margin cap cannot be overridden"):
        PublishDesk(repo, agent).execute(QT, "d@x.com")


def test_an_incomplete_book_is_refused_with_the_engines_reason():
    repo = FakeRepo()
    agent = FakeAgent(risk={**risk_report("incomplete", within_limits=False),
                            "blocksPublish": True,
                            "blockers": [{"term": "incomplete", "detail": "the day's book is "
                                          "incomplete; save again"}]})
    with pytest.raises(DeskConflict, match="^the day's book is incomplete; save again$"):
        PublishDesk(repo, agent).execute(QT, "d@x.com")


def test_an_approved_override_waives_the_breaches():
    repo = FakeRepo()
    _saved(repo)
    agent = FakeAgent(risk=risk_report("override", audit_id=99, within_limits=False,
                                       approved_override=True, breaches=["L_g"]))
    assert PublishDesk(repo, agent).execute(QT, "d@x.com")["command"]["kind"] == "publish"


@pytest.mark.parametrize("state", ["model", "no_book"])
def test_the_model_book_and_no_book_pass(state):
    repo = FakeRepo()
    agent = FakeAgent(risk=risk_report(state))
    assert PublishDesk(repo, agent).execute(QT, "d@x.com")["command"]["kind"] == "publish"
    assert agent.calls == [("Publish", 1)]


def test_positions_within_the_limits_pass():
    repo = FakeRepo()
    save_id = _saved(repo)
    agent = FakeAgent(risk=risk_report("desk", audit_id=save_id))
    assert PublishDesk(repo, agent).execute(QT, "d@x.com")["command"]["kind"] == "publish"


def test_approve_fails_closed_when_the_risk_check_is_unavailable():
    repo = FakeRepo()
    with pytest.raises(DeskConflict, match=r"The risk check is unavailable \(UNAVAILABLE\); try again"):
        PublishDesk(repo, FakeAgent(risk_down="UNAVAILABLE")).execute(QT, "d@x.com")
    assert repo.rows == []


def test_a_report_of_an_older_save_is_refused():
    repo = FakeRepo()
    first = _saved(repo)
    second = _saved(repo)
    agent = FakeAgent(risk=risk_report("desk", audit_id=first))
    with pytest.raises(DeskConflict, match=f"has not caught up with save #{second}; try again"):
        PublishDesk(repo, agent).execute(QT, "d@x.com")
    # A failed later save leaves the last done one as the book.
    repo.get_command(second)["status"] = "failed"
    assert PublishDesk(repo, agent).execute(QT, "d@x.com")["command"]["kind"] == "publish"


@pytest.mark.parametrize("status", ["pending", "running"])
def test_approve_is_refused_while_a_save_is_running(status):
    repo = FakeRepo()
    save_id = _saved(repo, status)
    agent = FakeAgent()
    with pytest.raises(DeskConflict, match=rf"A save is still running \(#{save_id}\)"):
        PublishDesk(repo, agent).execute(QT, "d@x.com")
    assert agent.risk_calls == []


def test_a_published_day_is_refused_as_published_not_by_the_risk_check():
    repo = FakeRepo()
    repo.published = {"published_by": "d@x.com", "published_at": NOW}
    with pytest.raises(DeskConflict, match="already published"):
        PublishDesk(repo, FakeAgent(risk_down="UNAVAILABLE")).execute(QT, "d@x.com")


def test_the_approval_page_carries_the_risk_report():
    repo = FakeRepo()
    request = repo.insert_command(QT["portfolio_id"], DAY, "override_request", "d@x.com", "why")
    request.update(token_hash=token_hash("tok"), token_expires_at=NOW + timedelta(hours=1))
    report = risk_report("desk", audit_id=1, within_limits=False, breaches=["L_g"])
    page = LookupApproval(repo, FakeAgent(risk=report), now=lambda: NOW).execute("tok")
    assert page["risk"] == report
    down = LookupApproval(repo, FakeAgent(risk_down="UNAVAILABLE"), now=lambda: NOW).execute("tok")
    assert down["risk"] == {"unavailable": "UNAVAILABLE"}


# -- C10: the A -> B -> C approval ----------------------------------------------------------

def test_approve_saves_b_and_queues_its_publish_after_the_save():
    repo, agent = FakeRepo(), FakeAgent()
    result = ApproveDesk(repo, agent, now=lambda: NOW).execute(
        QT, [{"symbol": "ZC.v.0", "quantity": 4, "expected": 3}], "lean in", "d@x.com")
    save, publish = result["save"], result["command"]
    assert save["kind"] == "save" and save["payload"]["changes"]
    assert publish["kind"] == "publish"
    assert publish["payload"] == {"flow": "auto", "after": save["id"]}
    # RunDesk first: the engine queues the publish behind it.
    assert agent.calls == [("RunDesk", save["id"]), ("Publish", publish["id"])]
    # No risk gate before the pass: the engine decides.
    assert agent.risk_calls == []


def test_approve_without_edits_approves_b_as_it_stands():
    repo, agent = FakeRepo(), FakeAgent()
    result = ApproveDesk(repo, agent, now=lambda: NOW).execute(QT, [], "as is", "d@x.com")
    assert result["save"]["payload"] == {"changes": []}
    assert result["command"]["payload"]["flow"] == "auto"


def test_approve_is_closed_from_10_and_needs_a_reason():
    repo = FakeRepo()
    with pytest.raises(DeskConflict, match="closed at 10:00"):
        ApproveDesk(repo, FakeAgent(), now=lambda: _ny(DAY, 10, 0)).execute(
            QT, [], "late", "d@x.com")
    with pytest.raises(DeskRuleError):
        ApproveDesk(repo, FakeAgent(), now=lambda: NOW).execute(QT, [], "", "d@x.com")
    with pytest.raises(DeskRuleError):
        ApproveDesk(repo, FakeAgent(), now=lambda: NOW).execute(QT, "nope", "r", "d@x.com")
    assert repo.rows == []


def _c_report(save_id, **over):
    report = risk_report("desk", audit_id=save_id, within_limits=False, breaches=["cap"])
    report.update(over)
    return report


def test_accept_c_publishes_the_engines_book_of_the_latest_save():
    repo = FakeRepo()
    save_id = _saved(repo)
    agent = FakeAgent(risk=_c_report(save_id))
    result = PublishDesk(repo, agent, now=lambda: NOW).execute(
        QT, "d@x.com", flow="accept_c", acknowledged=["ZT.v.0"])
    assert result["command"]["payload"] == {"flow": "accept_c", "after": save_id,
                                            "acknowledged": ["ZT.v.0"]}


@pytest.mark.parametrize("blockers, needle", [
    (["L_g"], r"^The engine's book \(C\) is over a cap \(L_g over its cap\): save within the caps or ask the VP or President"),
    (["MARGIN"], "the margin cap cannot be overridden"),
    (["refused"], r"over a cap \(refused over its cap\)$"),
])
def test_accept_c_refuses_a_c_the_engine_blocks(blockers, needle):
    repo = FakeRepo()
    save_id = _saved(repo)
    gate = risk_report(blockers=blockers)
    report = _c_report(save_id, blocksPublish=True, blockers=gate["blockers"])
    with pytest.raises(DeskConflict, match=needle):
        PublishDesk(repo, FakeAgent(risk=report), now=lambda: NOW).execute(
            QT, "d@x.com", flow="accept_c", acknowledged=[])


def test_accept_c_with_an_over_after_rounding_term_the_engine_passes_publishes():
    # R still over after rounding is reported, not a cap (decision 5).
    repo = FakeRepo()
    save_id = _saved(repo)
    report = _c_report(save_id, overLimitAfterRounding="R")
    result = PublishDesk(repo, FakeAgent(risk=report), now=lambda: NOW).execute(
        QT, "d@x.com", flow="accept_c", acknowledged=[])
    assert result["command"]["kind"] == "publish"


def test_accept_c_needs_a_finished_current_save_and_a_readable_check():
    repo = FakeRepo()
    with pytest.raises(DeskConflict, match="no finished save"):
        PublishDesk(repo, FakeAgent(), now=lambda: NOW).execute(
            QT, "d@x.com", flow="accept_c", acknowledged=[])
    running = _saved(repo, status="running")
    with pytest.raises(DeskConflict, match="still running"):
        PublishDesk(repo, FakeAgent(), now=lambda: NOW).execute(
            QT, "d@x.com", flow="accept_c", acknowledged=[])
    repo.get_command(running)["status"] = "done"
    with pytest.raises(DeskConflict, match="not the result of save"):
        PublishDesk(repo, FakeAgent(risk=_c_report(running - 1)), now=lambda: NOW).execute(
            QT, "d@x.com", flow="accept_c", acknowledged=[])
    with pytest.raises(DeskConflict, match="unavailable"):
        PublishDesk(repo, FakeAgent(risk_down="UNAVAILABLE"), now=lambda: NOW).execute(
            QT, "d@x.com", flow="accept_c", acknowledged=[])
    with pytest.raises(DeskRuleError):
        PublishDesk(repo, FakeAgent(), now=lambda: NOW).execute(
            QT, "d@x.com", flow="accept_c", acknowledged="ZT")
    with pytest.raises(DeskRuleError):
        PublishDesk(repo, FakeAgent(), now=lambda: NOW).execute(QT, "d@x.com", flow="bogus")


# --- a future day (Dominick 2026-10-18, replacing D-43) ------------------------


def test_a_future_day_is_approved_once_its_book_exists():
    # No reason to wait for the day itself: the model's book exists, so the desk decides.
    eve = lambda: _ny(DAY - timedelta(days=1), 20, 0)  # noqa: E731  the evening before
    for run, kind in [
        (lambda repo, agent: PublishDesk(repo, agent, now=eve).execute(QT, "d@x.com"), "publish"),
        (lambda repo, agent: RequestOverride(repo, agent, now=eve).execute(QT, "r", "d@x.com"),
         "override_request"),
        (lambda repo, agent: SaveDeskEdit(repo, agent, now=eve).execute(
            QT, [{"symbol": "ZC.v.0", "quantity": 0, "expected": 3}], "r", "d@x.com"), "save"),
    ]:
        repo = FakeRepo()
        run(repo, FakeAgent())
        assert [r["kind"] for r in repo.rows] == [kind]


# --- approve with or without the e-mail; Send (D-66) ----------------------------------------


def test_approve_and_publish_can_hold_the_email():
    early = lambda: _ny(DAY, 9, 0)  # noqa: E731
    repo, agent = FakeRepo(), FakeAgent()
    result = ApproveDesk(repo, agent, now=early).execute(QT, [], "r", "d@x.com", email=False)
    assert result["command"]["payload"] == {"flow": "auto", "after": result["save"]["id"],
                                            "email": False}
    repo, agent = FakeRepo(), FakeAgent()
    command = PublishDesk(repo, agent, now=early).execute(QT, "d@x.com", email=False)["command"]
    assert command["payload"] == {"email": False}
    repo, agent = FakeRepo(), FakeAgent()
    command = PublishDesk(repo, agent, now=early).execute(QT, "d@x.com")["command"]
    assert "email" not in (command["payload"] or {})        # on by default
    with pytest.raises(DeskRuleError, match="email must be true or false"):
        PublishDesk(FakeRepo(), FakeAgent(), now=early).execute(QT, "d@x.com", email="no")


def test_the_desk_state_says_whether_the_approval_held_the_email():
    repo, _agent = _approved()
    repo.rows[0]["payload"] = {"email": False}
    state = GetDeskState(repo, FakeAgent(), now=lambda: _ny(DAY, 9, 0)).execute(QT)
    assert state["published"]["email"] is False


def test_send_emails_todays_published_unsent_book():
    repo, agent = _approved()
    result = SendDesk(repo, agent, now=lambda: _ny(DAY, 11, 0)).execute(QT, "d@x.com")
    assert result["command"]["payload"] == {"flow": "send"}
    assert agent.calls[-1] == ("Publish", result["command"]["id"])


def test_send_is_refused_for_another_day_unapproved_or_sent():
    with pytest.raises(DeskConflict, match="Only today's book is e-mailed"):
        repo, agent = _approved()
        SendDesk(repo, agent, now=lambda: _ny(DAY + timedelta(days=1), 8, 0)).execute(
            QT, "d@x.com")
    with pytest.raises(DeskConflict, match="not approved"):
        SendDesk(FakeRepo(), FakeAgent(), now=lambda: _ny(DAY, 11, 0)).execute(QT, "d@x.com")
    repo, agent = _approved(sent_at=_ny(DAY, 9, 30))
    with pytest.raises(DeskConflict, match="already been e-mailed"):
        SendDesk(repo, agent, now=lambda: _ny(DAY, 11, 0)).execute(QT, "d@x.com")


def test_state_carries_todays_model_run_status_from_the_engine():
    # D-56: the page shows running / failed / refused from GetRunStatus, for today (New York),
    # even while the desk still shows an earlier book or none.
    agent = FakeAgent()
    agent.status = {"state": "failed", "startedAt": "2026-10-09T10:45:00+00:00",
                    "finishedAt": None, "message": "strict_assertion"}
    now = lambda: datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)

    state = GetDeskState(FakeRepo(), agent, now=now).execute(QT)

    assert state["runStatus"] == {"date": "2026-10-09", **agent.status}
    assert agent.status_calls == [(QT["portfolio_id"], date(2026, 10, 9))]


def test_state_says_when_the_run_status_cannot_be_read():
    agent = FakeAgent()
    agent.status_down = "UNAVAILABLE"
    state = GetDeskState(FakeRepo(), agent).execute(QT)
    assert state["runStatus"]["unavailable"] == "UNAVAILABLE"
