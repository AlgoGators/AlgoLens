"""Authentication HTTP routes."""

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from algolens.adapters.serializers.identity import (
    serialize_check_email,
    serialize_user_session,
)
from algolens.application.identity.use_cases import (
    AccountAlreadyRegistered,
    CheckEmail,
    DevLogin,
    DevLoginUnavailable,
    EmailNotAuthorized,
    InvalidCredentials,
    Login,
    Logout,
    PasswordPolicyViolation,
    RegisterUser,
    UserNotFound,
    VerifySession,
)
from algolens.domain.identity.password_policy import (
    MIN_PASSWORD_LENGTH,
    validate_password as _validate_password,
)
from algolens.infrastructure.config.dependencies import (
    check_password_hash,
    create_dev_auth_config,
    create_identity_dependencies,
    execute_query,
    generate_password_hash,
    get_db_connection,
)
from extensions import limiter

auth_bp = Blueprint("auth", __name__)


def _dev_mode_enabled():
    return create_dev_auth_config().is_enabled()


def _identity_dependencies():
    return create_identity_dependencies(
        execute_query_func=execute_query,
        connection_factory=get_db_connection,
        verify_func=check_password_hash,
        hash_func=generate_password_hash,
    )


def _json_session(user, status_code):
    _users, _hasher, sessions = _identity_dependencies()
    access_token = sessions.create_token(user)
    resp = jsonify(serialize_user_session(user))
    sessions.set_access_cookie(resp, access_token)
    return resp, status_code


def _dev_user_from_config(config):
    try:
        return DevLogin(config).execute()
    except ValueError:
        current_app.logger.warning(
            "[DEV_MODE] DEV_USER_ID is not an integer; falling back to 1"
        )

        class FallbackDevAuthConfig:
            def is_enabled(self):
                return config.is_enabled()

            def user_id(self):
                return 1

            def user_email(self):
                return config.user_email()

            def user_role(self):
                return config.user_role()

        return DevLogin(FallbackDevAuthConfig()).execute()


@auth_bp.route("/login", methods=["POST"])
@limiter.limit("10 per minute")
def login():
    current_app.logger.info("Login attempt started")

    try:
        data = request.get_json()
        if not data or not data.get("email") or not data.get("password"):
            current_app.logger.warning("Login failed: Missing email or password")
            return jsonify({"error": "Email and password are required"}), 400

        email = data["email"]
        password = data["password"]
        current_app.logger.info("Login attempt for email: %s", email)

        users, hasher, _sessions = _identity_dependencies()
        user = Login(users, hasher).execute(email, password)
        current_app.logger.info(
            "Login successful for email: %s, role: %s", email, user.role
        )
        return _json_session(user, 200)
    except InvalidCredentials:
        return jsonify({"error": "Invalid email or password"}), 401
    except Exception as exc:
        current_app.logger.error("Login error: %s", str(exc), exc_info=True)
        return jsonify({"error": "An internal error occurred during login"}), 500


@auth_bp.route("/verify", methods=["GET"])
@jwt_required()
def verify():
    current_user_id = get_jwt_identity()
    config = create_dev_auth_config()
    if config.is_enabled():
        dev_user = _dev_user_from_config(config)
        if str(dev_user.id) == str(current_user_id):
            return jsonify(serialize_user_session(dev_user)), 200

    users, _hasher, _sessions = _identity_dependencies()

    try:
        user = VerifySession(users).execute(current_user_id)
    except UserNotFound:
        return jsonify({"error": "User not found"}), 404

    return jsonify(serialize_user_session(user)), 200


@auth_bp.route("/logout", methods=["POST"])
def logout():
    Logout().execute()
    _users, _hasher, sessions = _identity_dependencies()
    resp = jsonify({"message": "Logged out"})
    sessions.clear_cookies(resp)
    return resp, 200


@auth_bp.route("/dev-login", methods=["POST"])
def dev_login():
    config = create_dev_auth_config()
    try:
        user = _dev_user_from_config(config)
    except DevLoginUnavailable:
        return jsonify({"error": "Not found"}), 404

    current_app.logger.warning(
        "[DEV_MODE] Issued dev-login cookie for %s (role=%s) -- auth is bypassed; "
        "never enable this in production",
        user.email,
        user.role,
    )
    return _json_session(user, 200)


@auth_bp.route("/check-email", methods=["POST"])
@limiter.limit("20 per minute")
def check_email():
    data = request.get_json()
    if not data or not data.get("email"):
        return jsonify({"error": "Email is required"}), 400

    users, _hasher, _sessions = _identity_dependencies()
    result = CheckEmail(users).execute(data["email"])
    return jsonify(serialize_check_email(result)), result.status_code


@auth_bp.route("/register", methods=["POST"])
@limiter.limit("5 per minute")
def register():
    data = request.get_json()
    if (
        not data
        or not data.get("email")
        or not data.get("password")
        or not data.get("first_name")
        or not data.get("last_name")
    ):
        return jsonify(
            {"error": "Email, password, first name, and last name are required"}
        ), 400

    users, hasher, _sessions = _identity_dependencies()
    try:
        user = RegisterUser(users, hasher).execute(
            data["email"],
            data["password"],
            data["first_name"],
            data["last_name"],
        )
    except PasswordPolicyViolation as exc:
        return jsonify({"error": str(exc)}), 400
    except EmailNotAuthorized:
        return jsonify({"error": "Email not authorized. Contact an administrator."}), 403
    except AccountAlreadyRegistered:
        return jsonify({"error": "Account already registered. Please login."}), 400

    return _json_session(user, 201)
