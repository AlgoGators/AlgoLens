"""Screen access: the domain rules, /api/me/screens and the admin routes."""

import pytest
from flask_jwt_extended import create_access_token, get_csrf_token

from algolens.application.identity.screen_access import (
    GetUserScreens,
    ScreenAccessUnavailable,
)
from algolens.domain.identity.screens import (
    ScreenRuleError,
    grant_changes,
    is_admin,
    legacy_screens,
    ordered,
    validate_screens,
)
from app import app


def _login(client, identity="7", role="general_member", email="user@x.com"):
    with app.app_context():
        token = create_access_token(identity=identity, additional_claims={"role": role, "email": email})
        csrf = get_csrf_token(token)
    client.set_cookie("access_token_cookie", token)
    return {"X-CSRF-TOKEN": csrf}


# --- domain -------------------------------------------------------------------


def test_validate_screens_dedupes_and_refuses_unknowns():
    assert validate_screens(["qt", "member", "qt"]) == ("member", "qt")
    assert validate_screens([]) == ()
    for bad in (["admin"], [None], "member", None, [1]):
        with pytest.raises(ScreenRuleError):
            validate_screens(bad)


def test_ordered_is_the_landing_order():
    assert ordered(["investor", "member", "qt", "bogus"]) == ["qt", "member", "investor"]
    assert ordered(None) == []


def test_grant_changes():
    assert grant_changes(["member"], ["qt", "member"]) == (("qt",), ())
    assert grant_changes(["member", "qt"], []) == ((), ("member", "qt"))


def test_admin_is_exec_board():
    assert is_admin("exec_board") and is_admin("admin")
    assert not is_admin("general_member") and not is_admin("team_lead") and not is_admin(None)


def test_legacy_fallback_matches_the_003_backfill():
    assert legacy_screens("exec_board") == ["qt", "member"]
    assert legacy_screens("team_lead") == ["member"]
    assert legacy_screens("general_member") == ["member"]
    assert legacy_screens(None) == []
    assert legacy_screens("investor") == []


def test_get_user_screens_falls_back_only_when_the_table_is_missing():
    class Missing:
        def screens_for(self, user_id):
            raise ScreenAccessUnavailable("no table")

    class Empty:
        def screens_for(self, user_id):
            return []

    calls = []
    assert GetUserScreens(Missing(), on_fallback=lambda: calls.append(1)).execute(1, "team_lead") == [
        "member",
    ]
    assert calls == [1]
    # With the table present, no row means no screen for anyone but an admin.
    assert GetUserScreens(Empty()).execute(1, "team_lead") == []


def test_an_admin_holds_every_screen():
    class Empty:
        def screens_for(self, user_id):
            raise AssertionError("an admin's grants are not consulted")

    for role in ("exec_board", "admin"):
        assert GetUserScreens(Empty()).execute(1, role) == ["qt", "member", "investor"]


# --- /api/me/screens ----------------------------------------------------------


def test_me_screens_reads_the_grants(client, screen_access):
    screen_access.screens["7"] = ["investor", "member"]
    _login(client)
    body = client.get("/api/me/screens").get_json()
    assert body == {"screens": ["member", "investor"], "is_admin": False}


def test_me_screens_for_an_admin_is_every_screen_and_the_admin_tab(client, screen_access):
    screen_access.screens["7"] = []
    _login(client, role="exec_board")
    assert client.get("/api/me/screens").get_json() == {
        "screens": ["qt", "member", "investor"],
        "is_admin": True,
    }


def test_me_screens_requires_login(client):
    assert client.get("/api/me/screens").status_code == 401


def test_a_revoke_takes_effect_on_the_next_request(client, screen_access, monkeypatch):
    import algolens.adapters.http.portfolio as portfolio_http

    class NoIncubation:
        def list_incubating_strategies(self):
            return []

    monkeypatch.setattr(portfolio_http, "create_portfolio_dependencies", lambda: (None, NoIncubation()))
    screen_access.screens["7"] = ["member"]
    _login(client)
    assert client.get("/portfolio/incubation").status_code == 200
    screen_access.screens["7"] = []
    assert client.get("/portfolio/incubation").status_code == 403


# --- admin --------------------------------------------------------------------


def test_admin_routes_refuse_non_admins(client, screen_access):
    screen_access.screens["7"] = ["member", "qt", "investor"]
    headers = _login(client, role="general_member")
    assert client.get("/api/admin/users").status_code == 403
    assert client.put("/api/admin/users/7/screens", json={"screens": []}, headers=headers).status_code == 403
    assert client.get("/api/admin/reports").status_code == 403


def test_admin_lists_users(client, screen_access):
    screen_access.screens["3"] = ["investor"]
    _login(client, role="exec_board")
    users = client.get("/api/admin/users").get_json()["users"]
    assert users[0]["id"] == 3 and users[0]["screens"] == ["investor"]


def test_admin_sets_screens_and_it_is_recorded(client, screen_access):
    screen_access.screens["3"] = ["member"]
    headers = _login(client, role="exec_board", email="Admin@X.com")
    response = client.put("/api/admin/users/3/screens", json={"screens": ["qt", "investor"]}, headers=headers)
    assert response.status_code == 200
    assert response.get_json() == {
        "id": 3,
        "screens": ["qt", "investor"],
        "granted": ["investor", "qt"],
        "revoked": ["member"],
    }
    assert screen_access.set_calls[-1][2] == "admin@x.com"


def test_admin_set_screens_refusals(client, screen_access):
    screen_access.screens["3"] = ["member"]
    headers = _login(client, role="exec_board")
    assert client.put("/api/admin/users/3/screens", json={"screens": ["root"]}, headers=headers).status_code == 400
    assert client.put("/api/admin/users/3/screens", json={"nope": 1}, headers=headers).status_code == 400
    assert client.put("/api/admin/users/404/screens", json={"screens": []}, headers=headers).status_code == 404


def test_admin_writes_need_the_csrf_token(client, screen_access):
    screen_access.screens["3"] = ["member"]
    _login(client, role="exec_board")
    assert client.put("/api/admin/users/3/screens", json={"screens": []}).status_code == 401


# --- the role is read from auth.users on every request, never from the token -----


def test_a_demoted_admin_loses_admin_on_the_next_request(client, screen_access):
    screen_access.screens["7"] = ["member"]
    headers = _login(client, role="exec_board")
    assert client.get("/api/admin/users").status_code == 200
    screen_access.roles["7"] = "general_member"  # demoted in the database; the token still says exec_board
    assert client.get("/api/admin/users").status_code == 403
    assert client.put("/api/admin/users/8/screens", json={"screens": ["qt"]},
                      headers=headers).status_code == 403
    assert client.get("/api/me/screens").get_json() == {"screens": ["member"], "is_admin": False}
    assert client.get("/api/investor/reports").status_code == 403


def test_a_promoted_member_is_admin_on_the_next_request(client, screen_access):
    screen_access.screens["7"] = ["member"]
    _login(client, role="general_member")
    assert client.get("/api/admin/users").status_code == 403
    screen_access.roles["7"] = "exec_board"
    assert client.get("/api/admin/users").status_code == 200


def test_a_deleted_user_keeps_no_access_with_a_live_token(client, screen_access):
    screen_access.screens["7"] = ["member", "investor", "qt"]
    _login(client, role="exec_board")
    screen_access.roles["7"] = None  # the auth.users row is gone
    assert client.get("/api/me/screens").get_json() == {"screens": [], "is_admin": False}
    assert client.get("/api/admin/users").status_code == 403
    assert client.get("/portfolio/portfolios").status_code == 403
    assert client.get("/api/investor/reports").status_code == 403
