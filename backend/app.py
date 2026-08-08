from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from werkzeug.middleware.proxy_fix import ProxyFix
import os
import logging
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv
from pathlib import Path

from extensions import limiter

ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=ENV_PATH)

# Determine environment
ENV = os.getenv("FLASK_ENV", "production")
DEBUG = os.getenv("FLASK_DEBUG", "False").lower() == "true"
IS_PRODUCTION = ENV == "production"

app = Flask(__name__)

# Behind nginx: trust one proxy hop for X-Forwarded-For/-Proto so request.remote_addr
# is the real client IP (used for rate-limit keys and request logging) rather than
# the proxy's loopback address.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

# Configure CORS securely.
# In production, CORS_ORIGINS MUST be set to an explicit allow-list -- fail closed
# rather than defaulting to "*", which (with supports_credentials) would let any
# origin make credentialed requests.
if IS_PRODUCTION:
    cors_origins_raw = os.getenv("CORS_ORIGINS", "").strip()
    if not cors_origins_raw or cors_origins_raw == "*":
        raise RuntimeError(
            "CORS_ORIGINS must be set to an explicit comma-separated allow-list in "
            "production (not empty and not '*'). Refusing to start with a wildcard "
            "CORS policy alongside credentialed requests."
        )
    allowed_origins = [o.strip() for o in cors_origins_raw.split(",") if o.strip()]
    CORS(
        app, supports_credentials=True, resources={r"/*": {"origins": allowed_origins}}
    )
else:
    # Development: allow everything
    CORS(app, supports_credentials=True)

# Configure logging
if not app.debug:
    # Create logs directory if it doesn't exist
    if not os.path.exists("logs"):
        os.mkdir("logs")

    # File handler for all logs
    file_handler = RotatingFileHandler(
        "logs/algolens.log", maxBytes=10240000, backupCount=10
    )
    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]"
        )
    )
    file_handler.setLevel(logging.INFO)
    app.logger.addHandler(file_handler)

# Console handler for immediate debugging
console_handler = logging.StreamHandler()
console_handler.setFormatter(
    logging.Formatter("%(asctime)s %(levelname)s: %(message)s")
)
console_handler.setLevel(logging.DEBUG)
app.logger.addHandler(console_handler)

app.logger.setLevel(logging.DEBUG)
app.logger.info("AlgoLens backend startup")


# Log all requests
@app.before_request
def log_request_info():
    app.logger.info(
        "Request: %s %s from %s", request.method, request.path, request.remote_addr
    )
    if request.get_json(silent=True):
        # Log request body but mask sensitive fields
        data = request.get_json()
        safe_data = {k: ("***" if k in ["password"] else v) for k, v in data.items()}
        app.logger.debug("Request body: %s", safe_data)


@app.after_request
def log_response_info(response):
    app.logger.info(
        "Response: %s %s - Status %s",
        request.method,
        request.path,
        response.status_code,
    )

    # CORS debugging for production issues
    origin = request.headers.get("Origin")
    if origin:
        app.logger.info("[CORS] Request Origin: %s", origin)
        app.logger.info(
            "[CORS] Response Access-Control-Allow-Origin: %s",
            response.headers.get("Access-Control-Allow-Origin", "NOT SET"),
        )

        # Check if CORS headers are missing on error responses
        if response.status_code >= 400 and not response.headers.get(
            "Access-Control-Allow-Origin"
        ):
            app.logger.warning(
                "[CORS] WARNING: Error response missing CORS headers - browser may not show error details"
            )

    return response


# Handle preflight requests explicitly for debugging
@app.before_request
def handle_preflight():
    if request.method == "OPTIONS":
        app.logger.info(
            "[CORS] Preflight request from Origin: %s", request.headers.get("Origin")
        )
        app.logger.info(
            "[CORS] Access-Control-Request-Method: %s",
            request.headers.get("Access-Control-Request-Method"),
        )
        app.logger.info(
            "[CORS] Access-Control-Request-Headers: %s",
            request.headers.get("Access-Control-Request-Headers"),
        )


# JWT signing key. In production it MUST come from the environment -- fail closed
# rather than silently falling back to a well-known dev key, which would let anyone
# forge valid tokens. In development a generated ephemeral key is used if unset.
_jwt_secret = os.getenv("JWT_SECRET_KEY")
if not _jwt_secret:
    if IS_PRODUCTION:
        raise RuntimeError(
            "JWT_SECRET_KEY must be set in production. Refusing to start with a "
            "default/guessable signing key."
        )
    import secrets

    _jwt_secret = secrets.token_urlsafe(32)
    app.logger.warning(
        "JWT_SECRET_KEY not set; using an ephemeral dev key (tokens will not survive a restart)"
    )
app.config["JWT_SECRET_KEY"] = _jwt_secret

from datetime import timedelta

app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(seconds=43200)

jwt = JWTManager(app)
limiter.init_app(app)


# Handle JWT decode errors (e.g., old tokens with non-string subject) as 401
@jwt.invalid_token_loader
def invalid_token_callback(error_string):
    app.logger.warning(f"Invalid token: {error_string}")
    return jsonify(
        {"error": "Invalid or expired token. Please log in again.", "msg": error_string}
    ), 401


@jwt.expired_token_loader
def expired_token_callback(jwt_header, jwt_payload):
    app.logger.info("Expired token used")
    return jsonify({"error": "Token has expired. Please log in again."}), 401


@jwt.unauthorized_loader
def missing_token_callback(error_string):
    app.logger.warning(f"Missing token: {error_string}")
    return jsonify({"error": "Authorization token is required."}), 401


@jwt.token_verification_failed_loader
def token_verification_failed_callback(jwt_header, jwt_payload):
    app.logger.warning("Token verification failed")
    return jsonify({"error": "Token verification failed. Please log in again."}), 401


from routes.auth import auth_bp
from routes.portfolio import portfolio_bp
from database import get_db_connection

app.register_blueprint(auth_bp, url_prefix="/auth")
app.register_blueprint(portfolio_bp, url_prefix="/portfolio")


# Health check endpoint for debugging connectivity
@app.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint - no auth required. Use for debugging connectivity."""
    app.logger.info("[HEALTH] Health check called")

    # This endpoint is unauthenticated, so the production response is deliberately
    # minimal: a bare status, no environment/debug/CORS config and no raw DB error
    # strings (which can leak the DB host, driver, and internal topology). The full
    # diagnostic detail is only returned in non-production and is always logged.
    health_status = {"status": "ok", "checks": {}}

    # Test database connection
    try:
        app.logger.info("[HEALTH] Testing database connection...")
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1")
            result = cursor.fetchone()
        conn.close()
        health_status["checks"]["database"] = "ok"
        app.logger.info("[HEALTH] Database connection successful")
    except Exception as e:
        # Always log the full error server-side; only expose detail off-production.
        health_status["checks"]["database"] = (
            "error" if IS_PRODUCTION else f"error: {str(e)}"
        )
        health_status["status"] = "degraded"
        app.logger.error(
            f"[HEALTH] Database connection failed: {str(e)}", exc_info=True
        )

    if not IS_PRODUCTION:
        health_status["environment"] = ENV
        health_status["debug"] = DEBUG
        health_status["cors_origins"] = os.getenv("CORS_ORIGINS", "*")

    app.logger.info(f"[HEALTH] Health check result: {health_status}")
    return health_status, 200 if health_status["status"] == "ok" else 503


if __name__ == "__main__":
    # NEVER use debug=True in production - it exposes remote code execution vulnerability
    port = int(os.getenv("PORT", 5000))
    app.run(debug=DEBUG, port=port, host="0.0.0.0")
