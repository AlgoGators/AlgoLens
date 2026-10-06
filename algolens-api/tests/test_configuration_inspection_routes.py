"""Configuration inspection is a protected, explicitly scoped read."""

from tests.test_incubation_routes import _set_jwt_cookie
from algolens.application.configuration_inspection import ConfigurationInspectionService, InspectionError


URL = "/portfolio/strategies/trend/configuration?portfolio_id=BOOK"


def test_registered_inspection_get_returns_bounded_response(client, monkeypatch):
    import algolens.adapters.http.configuration_inspection as http

    class Reader:
        def read(self, registry_id, portfolio_id, read_at):
            return "unavailable", "not_published", portfolio_id

    monkeypatch.setattr(http, "create_configuration_inspection_service",
                        lambda: ConfigurationInspectionService(Reader()))
    _set_jwt_cookie(client, role="admin", identity="7")
    response = client.get(URL)
    assert response.status_code == 200
    assert set(response.json) == {
        "api_version", "scope", "read_at", "status", "reason", "publication"
    }
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json["status"] == "unavailable"
    assert response.json["reason"] == "not_published"
    assert response.json["publication"] is None


def test_login_and_current_stored_role_are_required(client, monkeypatch):
    import algolens.adapters.http.configuration_inspection as http

    class Reader:
        def read(self, *_):
            raise AssertionError("denied request reached inspection data")

    monkeypatch.setattr(http, "create_configuration_inspection_service",
                        lambda: ConfigurationInspectionService(Reader()))
    assert client.get(URL).status_code == 401
    _set_jwt_cookie(client, role="admin", identity="7", current_role="subscriber_individual")
    denied = client.get(URL)
    assert denied.status_code == 403
    assert denied.headers["Cache-Control"] == "no-store"
    client.current_users.remove("7")
    assert client.get(URL).status_code == 403


def test_required_book_and_membership_error_are_sanitized(client, monkeypatch):
    import algolens.adapters.http.configuration_inspection as http

    class Reader:
        def read(self, *_):
            raise InspectionError("not_a_member_of_book", 400)

    monkeypatch.setattr(http, "create_configuration_inspection_service",
                        lambda: ConfigurationInspectionService(Reader()))
    _set_jwt_cookie(client, role="admin", identity="7")
    missing = client.get("/portfolio/strategies/trend/configuration")
    assert missing.status_code == 400
    assert missing.json["code"] == "missing_portfolio_id"
    nonmember = client.get(URL)
    assert nonmember.status_code == 400
    assert nonmember.json["code"] == "not_a_member_of_book"
    assert nonmember.headers["Cache-Control"] == "no-store"


def test_storage_exception_cannot_escape_in_response(client, monkeypatch):
    import algolens.adapters.http.configuration_inspection as http

    class Reader:
        def read(self, *_):
            raise RuntimeError("synthetic-private-sentinel")

    monkeypatch.setattr(http, "create_configuration_inspection_service",
                        lambda: ConfigurationInspectionService(Reader()))
    _set_jwt_cookie(client, role="admin", identity="7")
    response = client.get(URL)
    assert response.status_code == 503
    assert response.json["code"] == "storage_unavailable"
    assert "synthetic-private-sentinel" not in response.get_data(as_text=True)
