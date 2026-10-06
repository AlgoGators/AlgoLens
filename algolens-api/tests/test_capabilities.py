from types import SimpleNamespace

from flask_jwt_extended import create_access_token


def test_role_bundle_and_qt_grants_are_intersected_fail_closed():
    from algolens.domain.identity.capabilities import resolve_capabilities

    john = resolve_capabilities(
        "general_member",
        grants=[{"capability": "qt_submit", "active": True}],
        mappings=[],
    )
    assert "view_internal" in john
    assert "view_qt_platform" in john
    assert "edit_qt_book" in john
    assert "publish_qt_book" in john
    assert "approve_qt_override" not in john

    hemdutt = resolve_capabilities(
        "exec_board",
        grants=[{"capability": "qt_approve", "active": True}],
        mappings=[{"person_id": "hemdutt_rao", "active": True}],
    )
    assert "view_qt_platform" in hemdutt
    assert "approve_qt_override" in hemdutt
    assert "edit_qt_book" not in hemdutt
    assert "manage_incubation" not in hemdutt
    assert "publish_qt_book" not in hemdutt


def test_unknown_role_or_ambiguous_approver_mapping_has_no_authority():
    from algolens.domain.identity.capabilities import resolve_capabilities

    assert resolve_capabilities("new_role", grants=[], mappings=[]) == ()
    assert "approve_qt_override" not in resolve_capabilities(
        "general_member",
        grants=[{"capability": "qt_approve", "active": True}],
        mappings=[
            {"person_id": "xander_robbins", "active": True},
            {"person_id": "hemdutt_rao", "active": True},
        ],
    )


def test_session_serializer_returns_sorted_capabilities():
    from algolens.adapters.serializers.identity import serialize_user_session

    user = SimpleNamespace(
        id=7, email="john@example.com", first_name="John", last_name="Riley",
        role="general_member",
    )
    payload = serialize_user_session(user, ("view_qt_platform", "view_internal"))
    assert payload["user"]["capabilities"] == ["view_internal", "view_qt_platform"]


def test_verify_returns_server_resolved_capabilities(client, current_users, monkeypatch):
    import app as app_module
    import algolens.adapters.http.auth as auth_http

    current_users.set("7", role="general_member", email="john@example.com")
    monkeypatch.setattr(auth_http, "_identity_dependencies", lambda: (current_users, None, None))
    monkeypatch.setattr(
        auth_http, "resolve_user_capabilities",
        lambda user: ("view_internal", "edit_qt_book"),
    )
    with app_module.app.app_context():
        token = create_access_token(identity="7", additional_claims={"role": "admin"})
    client.set_cookie("access_token_cookie", token)

    response = client.get("/auth/verify")

    assert response.status_code == 200
    assert response.get_json()["user"]["role"] == "general_member"
    assert response.get_json()["user"]["capabilities"] == ["edit_qt_book", "view_internal"]


def test_authority_store_failure_grants_no_capabilities(monkeypatch):
    import algolens.adapters.http.capability_guard as guard
    from flask import Flask

    monkeypatch.setattr(guard, "_authority_rows", lambda _user_id: (_ for _ in ()).throw(RuntimeError("offline")))
    app = Flask(__name__)
    with app.app_context():
        user = SimpleNamespace(id=7, role="admin")
        assert guard.resolve_user_capabilities(user) == ()
