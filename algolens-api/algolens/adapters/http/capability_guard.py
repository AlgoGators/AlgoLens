"""Default-deny Flask route policy and current-authority resolution."""

from dataclasses import dataclass

from flask import current_app, jsonify, request
from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request
from flask_jwt_extended.exceptions import JWTExtendedException

from algolens.application.identity.use_cases import UserNotFound
from algolens.domain.identity.capabilities import CAPABILITIES, resolve_capabilities
from algolens.infrastructure.config.dependencies import load_identity_authority_rows


@dataclass(frozen=True)
class RoutePolicy:
    kind: str
    capability: str | None = None


def _policy(kind: str, capability: str | None = None):
    value = RoutePolicy(kind, capability)

    def decorate(fn):
        fn.__algolens_route_policy__ = value
        return fn

    return decorate


open_route = _policy("open")
dev_only_route = _policy("dev_only")
session_route = _policy("session")
disabled_route = _policy("disabled")


def requires_capability(capability: str):
    if capability not in CAPABILITIES:
        raise ValueError("unknown_capability")
    return _policy("capability", capability)


_authority_rows = load_identity_authority_rows


def resolve_user_capabilities(user) -> tuple[str, ...]:
    """Use stored role plus current QT grants; an unavailable authority store fails closed."""

    try:
        grants, mappings = _authority_rows(user.id)
    except Exception:
        current_app.logger.warning("Capability authority lookup unavailable; all authority denied")
        if current_app.config.get("ALGOLENS_IS_PRODUCTION", True) is False:
            return resolve_capabilities(user.role)
        return ()
    return resolve_capabilities(user.role, grants=grants, mappings=mappings)


def current_user_and_capabilities():
    # Reuse the established HTTP current-user boundary so controlled
    # development identities and injected repositories cannot disagree with
    # the capability guard. The local import avoids the portfolio -> guard
    # module cycle during route registration.
    from algolens.adapters.http import portfolio as portfolio_http

    subject = get_jwt_identity()
    user = portfolio_http._current_user()
    if str(user.id) != str(subject):
        raise UserNotFound()
    return user, resolve_user_capabilities(user)


def _rule_rows(app):
    for rule in app.url_map.iter_rules():
        if rule.endpoint == "static":
            continue
        for method in sorted(set(rule.methods) - {"HEAD", "OPTIONS"}):
            yield method, rule.rule, rule.endpoint


def unclassified_routes(app, *, explicitly_open_endpoints=frozenset()):
    missing = []
    for method, path, endpoint in _rule_rows(app):
        view = app.view_functions[endpoint]
        if endpoint not in explicitly_open_endpoints and getattr(view, "__algolens_route_policy__", None) is None:
            missing.append((method, path, endpoint))
    return tuple(missing)


def install_capability_guard(app, *, explicitly_open_endpoints=frozenset()):
    """Install the T5/T6 integration hook. Unknown routes are denied at runtime."""

    explicitly_open_endpoints = frozenset(explicitly_open_endpoints)

    @app.before_request
    def enforce_declared_capability():
        endpoint = request.endpoint
        if endpoint in explicitly_open_endpoints:
            return None
        view = app.view_functions.get(endpoint) if endpoint else None
        policy = getattr(view, "__algolens_route_policy__", None)
        if policy is None:
            return jsonify({"error": "Insufficient permissions"}), 403
        if policy.kind == "open":
            return None
        if policy.kind == "dev_only":
            return None if not app.config.get("ALGOLENS_IS_PRODUCTION", True) else (jsonify({"error": "Not found"}), 404)
        if policy.kind == "disabled":
            return jsonify({"error": "Not found"}), 404
        try:
            verify_jwt_in_request()
        except JWTExtendedException:
            return jsonify({"error": "Authentication required"}), 401
        try:
            if policy.kind == "session":
                return None
            _user, capabilities = current_user_and_capabilities()
        except UserNotFound:
            return jsonify({"error": "Insufficient permissions"}), 403
        except Exception:
            current_app.logger.error("Authorization lookup failed")
            return jsonify({"error": "Authorization check failed"}), 503
        if policy.kind != "capability" or policy.capability not in capabilities:
            return jsonify({"error": "Insufficient permissions"}), 403
        return None

    return enforce_declared_capability
