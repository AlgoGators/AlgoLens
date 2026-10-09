"""QT desk HTTP routes: the flag, permissions and status mapping."""

from datetime import timedelta

import pytest
from flask_jwt_extended import create_access_token, get_csrf_token

import algolens.adapters.http.desk as desk_http
from algolens.domain.qt.desk import token_hash
from algolens.infrastructure.config.qt import load_qt_settings
from app import app
from test_qt_desk_use_cases import NOW, FakeAgent, FakeRepo

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
    for path in ("save", "override-request", "publish"):
        response = client.post(
            f"/portfolio/desk/QT_CONSERVATIVE_PORTFOLIO/{path}",
            json={"reason": "r", "changes": [{"symbol": "ZC.v.0", "quantity": 1}]},
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
        json={"changes": [{"symbol": "ZC.v.0", "quantity": 0}], "reason": "flatten"},
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
        ({"changes": [{"symbol": "ZC.v.0", "quantity": 1}]}, 400),  # no reason
        ({"changes": [{"symbol": "ZC.v.0", "quantity": 1.5}], "reason": "r"}, 400),
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
        json={"changes": [{"symbol": "ZC.v.0", "quantity": 1}], "reason": "r"},
        headers=headers,
    )
    assert response.status_code == 409


def test_model_portfolio_is_not_editable(client, desk):
    headers = _login(client)
    response = client.post(
        "/portfolio/desk/QT_CONSERVATIVE_MODEL_PORTFOLIO/save",
        json={"changes": [{"symbol": "ZC.v.0", "quantity": 1}], "reason": "r"},
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
    row.update(token_hash=token_hash("secret-token"), token_expires_at=NOW + timedelta(days=3650))
    return row


def test_approval_flow_for_an_approver(client, desk):
    request = _request_with_token(client, desk)
    headers = _login(client, email="P@x.com", role="investor")  # approvers need no desk role

    page = client.post("/portfolio/desk/approval", json={"token": "secret-token"}, headers=headers)
    assert page.status_code == 200
    body = page.get_json()
    assert body["request"]["id"] == request["id"]
    assert body["viewer"] == {"email": "P@x.com", "approver_role": "president", "is_requester": False}

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

    member = _login(client, email="member@x.com", role="general_member")
    assert client.post("/portfolio/desk/approval", json={"token": "secret-token"}, headers=member).status_code == 200
    assert client.post(
        "/portfolio/desk/approval/decide", json={"token": "secret-token", "approved": True}, headers=member
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
