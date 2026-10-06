from flask import Flask


def test_unclassified_route_is_rejected_and_reported():
    from algolens.adapters.http.capability_guard import (
        install_capability_guard,
        unclassified_routes,
    )

    app = Flask(__name__)

    @app.get("/forgotten")
    def forgotten():
        return {"ok": True}

    assert unclassified_routes(app) == (("GET", "/forgotten", "forgotten"),)
    install_capability_guard(app)
    response = app.test_client().get("/forgotten")
    assert response.status_code == 403
    assert response.get_json() == {"error": "Insufficient permissions"}


def test_actual_blueprint_route_map_has_no_unclassified_rule():
    from algolens.adapters.http.capability_guard import _rule_rows, unclassified_routes
    from algolens.infrastructure.config.app_factory import create_app

    app = create_app()
    assert unclassified_routes(
        app, explicitly_open_endpoints={"version", "health_check"}
    ) == ()
    assert len(tuple(_rule_rows(app))) == 42


def test_declared_capability_is_enforced_from_current_server_authority(monkeypatch):
    from flask_jwt_extended import JWTManager, create_access_token
    import algolens.adapters.http.capability_guard as guard

    app = Flask(__name__)
    app.config["JWT_SECRET_KEY"] = "test-secret-key-that-is-at-least-32-bytes"
    JWTManager(app)

    @app.get("/managed")
    @guard.requires_capability("manage_books")
    def managed():
        return {"ok": True}

    guard.install_capability_guard(app)
    with app.app_context():
        token = create_access_token(identity="7")
    client = app.test_client()
    headers = {"Authorization": f"Bearer {token}"}

    assert client.get("/managed").status_code == 401
    monkeypatch.setattr(guard, "current_user_and_capabilities", lambda: (object(), ("view_internal",)))
    assert client.get("/managed", headers=headers).status_code == 403
    monkeypatch.setattr(guard, "current_user_and_capabilities", lambda: (object(), ("manage_books",)))
    assert client.get("/managed", headers=headers).status_code == 200
