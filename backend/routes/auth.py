from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import (
    create_access_token,
    set_access_cookies,
    unset_jwt_cookies,
    jwt_required,
    get_jwt_identity,
)
from werkzeug.security import check_password_hash, generate_password_hash
from database import execute_query
from extensions import limiter

auth_bp = Blueprint("auth", __name__)

# Minimum password length enforced server-side (the client mirrors this in
# RegisterView.tsx, but the server is the authority).
MIN_PASSWORD_LENGTH = 12


def _validate_password(password):
    """Return an error message if the password is unacceptable, else None."""
    if not isinstance(password, str) or len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters long"
    return None


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

        current_app.logger.info(f"Login attempt for email: {email}")

        query = "SELECT * FROM auth.users WHERE email = %s"
        current_app.logger.debug(f"Executing query: {query} with email: {email}")

        user = execute_query(query, (email,), fetch_one=True)

        if not user:
            current_app.logger.warning(
                f"Login failed: User not found for email: {email}"
            )
            return jsonify({"error": "Invalid email or password"}), 401

        current_app.logger.debug(f"User found: {user.get('id')} - {email}")

        if not check_password_hash(user["password_hash"], password):
            current_app.logger.warning(
                f"Login failed: Invalid password for email: {email}"
            )
            return jsonify({"error": "Invalid email or password"}), 401

        current_app.logger.info(f"Password verified for email: {email}")

        access_token = create_access_token(
            identity=str(user["id"]),
            additional_claims={
                "email": user["email"],
                "role": user.get("role", "general_member"),
            },
        )

        current_app.logger.info(
            f"Login successful for email: {email}, role: {user.get('role', 'general_member')}"
        )

        # Deliver the token as an httpOnly cookie (plus the CSRF companion cookie).
        # The token is intentionally NOT returned in the body -- putting it there
        # would re-introduce the JS-readable token we are removing. The client reads
        # its logged-in identity from the `user` object and, on reload, from /verify.
        resp = jsonify(
            {
                "user": {
                    "id": user["id"],
                    "email": user["email"],
                    "first_name": user.get("first_name"),
                    "last_name": user.get("last_name"),
                    "role": user.get("role", "general_member"),
                }
            }
        )
        set_access_cookies(resp, access_token)
        return resp, 200

    except Exception as e:
        current_app.logger.error(f"Login error: {str(e)}", exc_info=True)
        return jsonify({"error": "An internal error occurred during login"}), 500


@auth_bp.route("/verify", methods=["GET"])
@jwt_required()
def verify():
    """Return the current user, authenticated via the httpOnly access cookie.

    The SPA calls this on load to restore the session: because the token lives in an
    httpOnly cookie the front-end JavaScript cannot read it, so it asks the server
    who it is. A missing/expired cookie yields a 401 (handled by the JWT loaders),
    which the client treats as "logged out" rather than an error.
    """
    current_user_id = get_jwt_identity()

    query = "SELECT * FROM auth.users WHERE id = %s"
    user = execute_query(query, (current_user_id,), fetch_one=True)

    if not user:
        return jsonify({"error": "User not found"}), 404

    return jsonify(
        {
            "user": {
                "id": user["id"],
                "email": user["email"],
                "first_name": user.get("first_name"),
                "last_name": user.get("last_name"),
                "role": user.get("role", "general_member"),
            }
        }
    ), 200


@auth_bp.route("/logout", methods=["POST"])
def logout():
    """Clear the auth cookies. Safe to call without a valid session (idempotent);
    the worst a forged cross-site call can do is log the user out, so no CSRF check
    or jwt_required is imposed here."""
    resp = jsonify({"message": "Logged out"})
    unset_jwt_cookies(resp)
    return resp, 200


@auth_bp.route("/check-email", methods=["POST"])
@limiter.limit("20 per minute")
def check_email():
    data = request.get_json()

    if not data or not data.get("email"):
        return jsonify({"error": "Email is required"}), 400

    email = data["email"]

    query = "SELECT id, email, password_hash FROM auth.users WHERE email = %s"
    user = execute_query(query, (email,), fetch_one=True)

    if not user:
        return jsonify(
            {
                "exists": False,
                "message": "Email not found. Contact an administrator to be added.",
            }
        ), 404

    has_password = user["password_hash"] is not None and user["password_hash"] != ""

    if has_password:
        return jsonify(
            {
                "exists": True,
                "registered": True,
                "message": "Account already registered. Please login.",
            }
        ), 200

    return jsonify(
        {
            "exists": True,
            "registered": False,
            "message": "Email found. Please complete registration.",
        }
    ), 200


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

    email = data["email"]
    password = data["password"]
    first_name = data["first_name"]
    last_name = data["last_name"]

    # Enforce the password policy server-side (authoritative; the client mirror is
    # only a UX convenience and can be bypassed).
    password_error = _validate_password(password)
    if password_error:
        return jsonify({"error": password_error}), 400

    check_query = "SELECT id, password_hash FROM auth.users WHERE email = %s"
    user = execute_query(check_query, (email,), fetch_one=True)

    if not user:
        return jsonify(
            {"error": "Email not authorized. Contact an administrator."}
        ), 403

    if user["password_hash"] and user["password_hash"] != "":
        return jsonify({"error": "Account already registered. Please login."}), 400

    hashed_password = generate_password_hash(password)

    update_query = """
        UPDATE auth.users
        SET password_hash = %s, first_name = %s, last_name = %s
        WHERE email = %s
        RETURNING id, email, first_name, last_name, role
    """

    from database import get_db_connection

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                update_query, (hashed_password, first_name, last_name, email)
            )
            updated_user = cursor.fetchone()
            conn.commit()

            access_token = create_access_token(
                identity=str(updated_user["id"]),
                additional_claims={
                    "email": updated_user["email"],
                    "role": updated_user.get("role", "general_member"),
                },
            )

            # Same cookie-based delivery as /login (see the note there).
            resp = jsonify(
                {
                    "user": {
                        "id": updated_user["id"],
                        "email": updated_user["email"],
                        "first_name": updated_user.get("first_name"),
                        "last_name": updated_user.get("last_name"),
                        "role": updated_user.get("role", "general_member"),
                    }
                }
            )
            set_access_cookies(resp, access_token)
            return resp, 201
    finally:
        conn.close()
