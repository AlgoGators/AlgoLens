"""QT desk HTTP routes: the flag, permissions and status mapping."""

from datetime import timedelta

import pytest
from flask_jwt_extended import create_access_token, get_csrf_token

import algolens.adapters.http.desk as desk_http
import algolens.application.qt.use_cases as use_cases
from algolens.domain.qt.desk import token_hash
from algolens.infrastructure.config.qt import load_qt_settings
from app import app
from test_qt_desk_use_cases import NOW, FakeAgent, FakeRepo, risk_report

REGISTRY = {
    "QT_CONSERVATIVE_PORTFOLIO": {
        "id": "qt_conservative",
        "portfolio_id": "QT_CONSERVATIVE_PORTFOLIO",
        "strategy_type": "LIVE_TREND_FOLLOWING",
        "name": "QT",
        "portfolio_group": "qt_conservative",
        "desk_editable": True,
    },
    "QT_CONSERVATIVE_MODEL_PORTFOLIO": {
        "id": "qt_conservative_model",
        "portfolio_id": "QT_CONSERVATIVE_MODEL_PORTFOLIO",
        "strategy_type": "LIVE_TREND_FOLLOWING",
        "name": "QT model",
        "portfolio_group": "qt_conservative",
        "desk_editable": False,
    },
}


class FakeRegistry:
    def get_portfolio(self, portfolio_id):
        return REGISTRY.get(portfolio_id)


@pytest.fixture
def desk(monkeypatch):
    repo, agent = FakeRepo(), FakeAgent()
    monkeypatch.setattr(use_cases, "_utcnow", lambda: NOW)  # before the 09:30 cutoff
    monkeypatch.setenv("QT_DESK_ENABLED", "true")
    monkeypatch.setenv("QT_APPROVERS", "vp=vp@x.com,president=p@x.com")
    monkeypatch.setattr(
        desk_http, "create_desk_dependencies", lambda: (repo, agent, load_qt_settings())
    )
    monkeypatch.setattr(
        desk_http, "create_portfolio_dependencies", lambda: (FakeRegistry(), None)
    )
    return repo, agent


def _login(client, email="desk@x.com", role="admin"):
    with app.app_context():
        token = create_access_token(identity="7", additional_claims={"role": role, "email": email})
        csrf = get_csrf_token(token)
    client.set_cookie("access_token_cookie", token)
    return {"X-CSRF-TOKEN": csrf}


def test_every_desk_route_is_404_while_the_flag_is_off(client, desk, monkeypatch):
    monkeypatch.setenv("QT_DESK_ENABLED", "false")
    headers = _login(client)
    assert client.get("/portfolio/desk/QT_CONSERVATIVE_PORTFOLIO").status_code == 404
    assert client.get("/portfolio/desk/QT_CONSERVATIVE_PORTFOLIO/symbols").status_code == 404
    for path in ("save", "override-request", "publish", "rescind"):
        response = client.post(
            f"/portfolio/desk/QT_CONSERVATIVE_PORTFOLIO/{path}",
            json={"reason": "r", "changes": [{"symbol": "ZC.v.0", "quantity": 1, "expected": 3}]},
            headers=headers,
        )
        assert response.status_code == 404, path
    assert client.post("/portfolio/desk/approval", json={"token": "t"}, headers=headers).status_code == 404
    assert desk[0].rows == []


def test_desk_routes_need_a_desk_user(client, desk):
    headers = _login(client, role="investor")
    assert client.get("/portfolio/desk/QT_CONSERVATIVE_PORTFOLIO").status_code == 403
    response = client.post(
        "/portfolio/desk/QT_CONSERVATIVE_PORTFOLIO/publish", json={}, headers=headers
    )
    assert response.status_code == 403


def test_write_routes_need_the_csrf_header(client, desk):
    _login(client)
    response = client.post("/portfolio/desk/QT_CONSERVATIVE_PORTFOLIO/publish", json={})
    assert response.status_code in (401, 422)
    assert desk[0].rows == []


def test_save_returns_201_with_the_pending_row(client, desk):
    repo, agent = desk
    headers = _login(client)

    response = client.post(
        "/portfolio/desk/QT_CONSERVATIVE_PORTFOLIO/save",
        json={"changes": [{"symbol": "ZC.v.0", "quantity": 0, "expected": 3}], "reason": "flatten"},
        headers=headers,
    )

    assert response.status_code == 201
    body = response.get_json()
    assert body["command"]["status"] == "pending"
    assert body["command"]["requested_by"] == "desk@x.com"
    assert agent.calls[0][0] == "RunDesk"

    polled = client.get(f"/portfolio/desk/commands/{body['command']['id']}")
    assert polled.status_code == 200 and polled.get_json()["kind"] == "save"


@pytest.mark.parametrize(
    "payload, status",
    [
        ({"changes": [{"symbol": "ZC.v.0", "quantity": 1, "expected": 3}]}, 400),  # no reason
        ({"changes": [{"symbol": "ZC.v.0", "quantity": 1.5, "expected": 3}], "reason": "r"}, 400),
        ({"changes": [], "reason": "r"}, 400),
        ([1, 2], 400),
    ],
)
def test_save_validation(client, desk, payload, status):
    headers = _login(client)
    response = client.post(
        "/portfolio/desk/QT_CONSERVATIVE_PORTFOLIO/save", json=payload, headers=headers
    )
    assert response.status_code == status
    assert desk[0].rows == []


def test_save_before_seeding_is_409(client, desk):
    desk[0].books["qt_proposal"] = []
    headers = _login(client)
    response = client.post(
        "/portfolio/desk/QT_CONSERVATIVE_PORTFOLIO/save",
        json={"changes": [{"symbol": "ZC.v.0", "quantity": 1, "expected": 3}], "reason": "r"},
        headers=headers,
    )
    assert response.status_code == 409


def test_model_portfolio_is_not_editable(client, desk):
    headers = _login(client)
    response = client.post(
        "/portfolio/desk/QT_CONSERVATIVE_MODEL_PORTFOLIO/save",
        json={"changes": [{"symbol": "ZC.v.0", "quantity": 1, "expected": 3}], "reason": "r"},
        headers=headers,
    )
    assert response.status_code == 403


def test_unknown_portfolio_is_404(client, desk):
    _login(client)
    assert client.get("/portfolio/desk/NOPE").status_code == 404


def test_publish_and_state(client, desk):
    headers = _login(client)
    assert client.post("/portfolio/desk/QT_CONSERVATIVE_PORTFOLIO/publish", json={}, headers=headers).status_code == 201
    assert client.post("/portfolio/desk/QT_CONSERVATIVE_PORTFOLIO/publish", json={}, headers=headers).status_code == 409
    state = client.get("/portfolio/desk/QT_CONSERVATIVE_PORTFOLIO").get_json()
    assert state["publish"]["kind"] == "publish"
    assert state["risk"]["state"] == "model"


def test_publish_outside_the_risk_limits_is_409_with_the_reason(client, desk):
    repo, agent = desk
    agent.risk = risk_report("desk", audit_id=0, within_limits=False, breaches=["L_g"],
                             blockers=["L_g"])
    headers = _login(client)
    response = client.post("/portfolio/desk/QT_CONSERVATIVE_PORTFOLIO/publish", json={}, headers=headers)
    assert response.status_code == 409
    assert response.get_json() == {
        "error": "The 2026-10-08 positions are over a cap (L_g over its cap): save within the "
        "caps or ask the VP or President to approve your positions"
    }
    assert repo.rows == []

    agent.risk_down = "UNAVAILABLE"
    response = client.post("/portfolio/desk/QT_CONSERVATIVE_PORTFOLIO/publish", json={}, headers=headers)
    assert response.status_code == 409
    assert response.get_json()["error"] == "The risk check is unavailable (UNAVAILABLE); try again"
    state = client.get("/portfolio/desk/QT_CONSERVATIVE_PORTFOLIO").get_json()
    assert state["risk"] == {"unavailable": "UNAVAILABLE"}


def _request_with_token(client, desk, requested_by="desk@x.com"):
    repo, _agent = desk
    headers = _login(client, email=requested_by)
    response = client.post(
        "/portfolio/desk/QT_CONSERVATIVE_PORTFOLIO/override-request",
        json={"reason": "intended breach"},
        headers=headers,
    )
    assert response.status_code == 201
    row = repo.get_command(response.get_json()["command"]["id"])
    row.update(token_hash=token_hash("secret-token"), token_expires_at=NOW + timedelta(days=3650),
               status="done")
    return row


def test_approval_flow_for_an_approver(client, desk):
    request = _request_with_token(client, desk)
    headers = _login(client, email="P@x.com", role="investor")  # approvers need no desk role

    page = client.post("/portfolio/desk/approval", json={"token": "secret-token"}, headers=headers)
    assert page.status_code == 200
    body = page.get_json()
    assert body["request"]["id"] == request["id"]
    assert body["viewer"] == {"email": "P@x.com", "approver_role": "president", "is_requester": False}
    assert body["risk"]["state"] == "model"

    decided = client.post(
        "/portfolio/desk/approval/decide",
        json={"token": "secret-token", "approved": True},
        headers=headers,
    )
    assert decided.status_code == 201
    assert decided.get_json()["command"]["approver_role"] == "president"

    again = client.post(
        "/portfolio/desk/approval/decide",
        json={"token": "secret-token", "approved": False},
        headers=headers,
    )
    assert again.status_code == 409


def test_approval_refusals(client, desk):
    _request_with_token(client, desk, requested_by="vp@x.com")

    stranger = _login(client, email="nobody@x.com", role="investor")
    assert client.post("/portfolio/desk/approval", json={"token": "secret-token"}, headers=stranger).status_code == 403

    # A member without the qt screen is not the desk: no approval page.
    member = _login(client, email="member@x.com", role="general_member")
    assert client.post("/portfolio/desk/approval", json={"token": "secret-token"}, headers=member).status_code == 403

    # A desk user (qt screen) may look, but only an approver decides.
    desk_user = _login(client, email="member@x.com", role="exec_board")
    assert client.post("/portfolio/desk/approval", json={"token": "secret-token"}, headers=desk_user).status_code == 200
    assert client.post(
        "/portfolio/desk/approval/decide", json={"token": "secret-token", "approved": True}, headers=desk_user
    ).status_code == 403

    own = _login(client, email="vp@x.com")
    assert client.post(
        "/portfolio/desk/approval/decide", json={"token": "secret-token", "approved": True}, headers=own
    ).status_code == 403

    assert client.post("/portfolio/desk/approval", json={"token": "wrong"}, headers=own).status_code == 404


def test_expired_link_is_410(client, desk):
    row = _request_with_token(client, desk)
    row["token_expires_at"] = NOW - timedelta(days=3650)
    headers = _login(client, email="p@x.com")
    assert client.post("/portfolio/desk/approval", json={"token": "secret-token"}, headers=headers).status_code == 410


# --- hardening (2026-10-09 spec) ---------------------------------------------


def test_a_stale_save_is_409_listing_the_changed_symbols(client, desk):
    headers = _login(client)
    response = client.post(
        "/portfolio/desk/QT_CONSERVATIVE_PORTFOLIO/save",
        json={"changes": [{"symbol": "ZC.v.0", "quantity": 1, "expected": 2}], "reason": "r"},
        headers=headers,
    )
    assert response.status_code == 409
    assert response.get_json()["changed"] == ["ZC.v.0"]


def test_a_save_without_the_quantity_shown_is_400(client, desk):
    headers = _login(client)
    response = client.post(
        "/portfolio/desk/QT_CONSERVATIVE_PORTFOLIO/save",
        json={"changes": [{"symbol": "ZC.v.0", "quantity": 1}], "reason": "r"},
        headers=headers,
    )
    assert response.status_code == 400


def test_a_unicode_digit_quantity_is_400_not_500(client, desk):
    headers = _login(client)
    response = client.post(
        "/portfolio/desk/QT_CONSERVATIVE_PORTFOLIO/save",
        json={"changes": [{"symbol": "ZC.v.0", "quantity": "²", "expected": 3}], "reason": "r"},
        headers=headers,
    )
    assert response.status_code == 400


def test_a_second_open_override_request_is_409(client, desk):
    headers = _login(client)
    path = "/portfolio/desk/QT_CONSERVATIVE_PORTFOLIO/override-request"
    assert client.post(path, json={"reason": "a"}, headers=headers).status_code == 201
    assert client.post(path, json={"reason": "b"}, headers=headers).status_code == 409


def test_override_requests_are_rate_limited_per_user(client, desk):
    repo, _agent = desk
    path = "/portfolio/desk/QT_CONSERVATIVE_PORTFOLIO/override-request"
    headers = _login(client, email="a@x.com")
    for _ in range(5):
        response = client.post(path, json={"reason": "r"}, headers=headers)
        assert response.status_code == 201
        repo.rows[-1]["status"] = "failed"  # frees the day for the next one
    assert client.post(path, json={"reason": "r"}, headers=headers).status_code == 429
    # Another user has a budget of their own.
    with app.app_context():
        token = create_access_token(identity="8", additional_claims={"role": "admin", "email": "b@x.com"})
        csrf = get_csrf_token(token)
    client.set_cookie("access_token_cookie", token)
    assert client.post(path, json={"reason": "r"}, headers={"X-CSRF-TOKEN": csrf}).status_code == 201


def test_refused_override_requests_do_not_use_the_budget(client, desk):
    path = "/portfolio/desk/QT_CONSERVATIVE_PORTFOLIO/override-request"
    headers = _login(client)
    assert client.post(path, json={"reason": "r"}, headers=headers).status_code == 201
    for _ in range(6):
        assert client.post(path, json={"reason": "r"}, headers=headers).status_code == 409


def test_a_stale_approval_is_409(client, desk):
    repo, _agent = desk
    _request_with_token(client, desk)
    repo.books["qt_proposal"][0]["quantity"] = 9  # the desk saved meanwhile
    headers = _login(client, email="p@x.com", role="investor")
    page = client.post("/portfolio/desk/approval", json={"token": "secret-token"}, headers=headers)
    assert page.get_json()["snapshotMatches"] is False
    decided = client.post(
        "/portfolio/desk/approval/decide",
        json={"token": "secret-token", "approved": True},
        headers=headers,
    )
    assert decided.status_code == 409


def test_liveness_needs_no_database(client):
    response = client.get("/health/live")
    assert response.status_code == 200 and response.get_json() == {"status": "ok"}


def test_approve_after_10_new_york_is_409_and_state_carries_the_clock(client, desk, monkeypatch):
    from datetime import datetime, timezone

    late = datetime(2026, 10, 8, 14, 0, tzinfo=timezone.utc)  # 10:00 EDT
    monkeypatch.setattr(use_cases, "_utcnow", lambda: late)
    headers = _login(client)
    response = client.post("/portfolio/desk/QT_CONSERVATIVE_PORTFOLIO/publish", json={}, headers=headers)
    assert response.status_code == 409
    assert "closed at 10:00 New York" in response.get_json()["error"]
    assert desk[0].rows == []
    state = client.get("/portfolio/desk/QT_CONSERVATIVE_PORTFOLIO").get_json()
    assert state["serverTime"] == late.isoformat()
    assert state["deadlines"]["approvalClosed"] is True
    assert state["deadlines"]["fallbackAt"] == "2026-10-08T10:00:00-04:00"


def test_rescind_and_state(client, desk):
    repo, agent = desk
    headers = _login(client)
    path = "/portfolio/desk/QT_CONSERVATIVE_PORTFOLIO/rescind"
    # Nothing approved yet: nothing to take back.
    assert client.post(path, json={}, headers=headers).status_code == 409
    repo.published = {"published_by": "desk@x.com", "published_at": NOW,
                      "publish_source": "desk", "sent_at": None}

    response = client.post(path, json={}, headers=headers)

    assert response.status_code == 201
    body = response.get_json()
    assert body["command"]["kind"] == "rescind" and body["command"]["status"] == "pending"
    assert body["command"]["requested_by"] == "desk@x.com"
    assert agent.calls[-1] == ("Rescind", body["command"]["id"])
    assert client.post(path, json={}, headers=headers).status_code == 409  # one open rescind
    state = client.get("/portfolio/desk/QT_CONSERVATIVE_PORTFOLIO").get_json()
    assert state["rescind"]["id"] == body["command"]["id"]


def test_rescind_needs_a_desk_user_and_the_csrf_header(client, desk):
    path = "/portfolio/desk/QT_CONSERVATIVE_PORTFOLIO/rescind"
    headers = _login(client, role="investor")
    assert client.post(path, json={}, headers=headers).status_code == 403
    _login(client)
    assert client.post(path, json={}).status_code in (401, 422)
    assert desk[0].rows == []


def test_rescind_from_0930_new_york_is_409(client, desk, monkeypatch):
    from datetime import datetime, timezone

    repo, _agent = desk
    repo.published = {"published_by": "desk@x.com", "published_at": NOW,
                      "publish_source": "desk", "sent_at": None}
    monkeypatch.setattr(
        use_cases, "_utcnow", lambda: datetime(2026, 10, 8, 13, 30, tzinfo=timezone.utc)
    )  # 09:30 EDT
    headers = _login(client)
    response = client.post(
        "/portfolio/desk/QT_CONSERVATIVE_PORTFOLIO/rescind", json={}, headers=headers
    )
    assert response.status_code == 409
    assert "can no longer be taken back" in response.get_json()["error"]
    assert repo.rows == []


def test_approve_saves_and_queues_the_publish(client, desk):
    repo, agent = desk
    headers = _login(client)
    response = client.post(
        "/portfolio/desk/QT_CONSERVATIVE_PORTFOLIO/approve",
        json={"changes": [{"symbol": "ZC.v.0", "quantity": 4, "expected": 3}], "reason": "lean"},
        headers=headers,
    )
    assert response.status_code == 201
    body = response.get_json()
    assert body["save"]["kind"] == "save"
    assert body["command"]["payload"] == {"flow": "auto", "after": body["save"]["id"]}
    assert [c[0] for c in agent.calls] == ["RunDesk", "Publish"]
    # The day is now publishing: a second approval waits for this one.
    again = client.post("/portfolio/desk/QT_CONSERVATIVE_PORTFOLIO/approve",
                        json={"changes": [], "reason": "again"}, headers=headers)
    assert again.status_code == 409


def test_publish_accept_c_takes_the_flow_from_the_body(client, desk):
    _repo, _agent = desk
    headers = _login(client)
    response = client.post("/portfolio/desk/QT_CONSERVATIVE_PORTFOLIO/publish",
                           json={"flow": "accept_c", "acknowledged": []}, headers=headers)
    assert response.status_code == 409  # no finished save yet
    assert "no finished save" in response.get_json()["error"]



def test_a_deleted_user_cannot_look_up_or_decide(client, desk, screen_access):
    # D-44: the token's e-mail claim alone is not trusted once the user is gone from auth.users.
    _request_with_token(client, desk)
    headers = _login(client, email="p@x.com", role="investor")
    screen_access.roles["7"] = None  # deleted after signing in

    page = client.post("/portfolio/desk/approval", json={"token": "secret-token"}, headers=headers)
    decided = client.post("/portfolio/desk/approval/decide",
                          json={"token": "secret-token", "approved": True}, headers=headers)

    assert page.status_code == 403 and "no longer exists" in page.get_json()["error"]
    assert decided.status_code == 403
    assert not any(r["kind"] == "override_decision" for r in desk[0].rows)
