"""Flask application composition."""

import logging
import os
from datetime import timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from werkzeug.middleware.proxy_fix import ProxyFix

from algolens.adapters.http.auth import auth_bp
from algolens.adapters.http.portfolio import portfolio_bp
from algolens.infrastructure.db.postgres import get_db_connection
from extensions import limiter

ENV_PATH = Path(__file__).resolve().parents[3] / ".env"


def create_app():
    load_dotenv(dotenv_path=ENV_PATH)

    env = os.getenv("FLASK_ENV", "production")
    debug = os.getenv("FLASK_DEBUG", "False").lower() == "true"
    is_production = env == "production"

    app = Flask(__name__)
    app.config["ALGOLENS_ENV"] = env
    app.config["ALGOLENS_DEBUG"] = debug
    app.config["ALGOLENS_IS_PRODUCTION"] = is_production

    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

    if is_production:
        cors_origins_raw = os.getenv("CORS_ORIGINS", "").strip()
        if not cors_origins_raw or cors_origins_raw == "*":
            raise RuntimeError(
                "CORS_ORIGINS must be set to an explicit comma-separated allow-list in "
                "production (not empty and not '*'). Refusing to start with a wildcard "
                "CORS policy alongside credentialed requests."
            )
        allowed_origins = [
            origin.strip() for origin in cors_origins_raw.split(",") if origin.strip()
        ]
        CORS(
            app,
            supports_credentials=True,
            resources={r"/*": {"origins": allowed_origins}},
        )
    else:
        CORS(app, supports_credentials=True)

    if not app.debug:
        if not os.path.exists("logs"):
            os.mkdir("logs")

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

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s: %(message)s")
    )
    console_handler.setLevel(logging.DEBUG)
    app.logger.addHandler(console_handler)

    app.logger.setLevel(logging.DEBUG)
    app.logger.info("AlgoLens backend startup")

    if os.getenv("DEV_MODE") == "1":
        if is_production:
            app.logger.warning(
                "[DEV_MODE] DEV_MODE=1 is set but FLASK_ENV=production -- the "
                "/auth/dev-login bypass is DISABLED for safety."
            )
        else:
            app.logger.warning(
                "[DEV_MODE] DEV_MODE=1 active -- POST /auth/dev-login will establish "
                "a session WITHOUT credentials. Local development only."
            )

    @app.before_request
    def log_request_info():
        app.logger.info(
            "Request: %s %s from %s",
            request.method,
            request.path,
            request.remote_addr,
        )
        if request.get_json(silent=True):
            data = request.get_json()
            safe_data = {
                key: ("***" if key in ["password"] else value)
                for key, value in data.items()
            }
            app.logger.debug("Request body: %s", safe_data)

    @app.after_request
    def log_response_info(response):
        app.logger.info(
            "Response: %s %s - Status %s",
            request.method,
            request.path,
            response.status_code,
        )

        origin = request.headers.get("Origin")
        if origin:
            app.logger.info("[CORS] Request Origin: %s", origin)
            app.logger.info(
                "[CORS] Response Access-Control-Allow-Origin: %s",
                response.headers.get("Access-Control-Allow-Origin", "NOT SET"),
            )

            if response.status_code >= 400 and not response.headers.get(
                "Access-Control-Allow-Origin"
            ):
                app.logger.warning(
                    "[CORS] WARNING: Error response missing CORS headers - browser may not show error details"
                )

        return response

    @app.before_request
    def handle_preflight():
        if request.method == "OPTIONS":
            app.logger.info(
                "[CORS] Preflight request from Origin: %s",
                request.headers.get("Origin"),
            )
            app.logger.info(
                "[CORS] Access-Control-Request-Method: %s",
                request.headers.get("Access-Control-Request-Method"),
            )
            app.logger.info(
                "[CORS] Access-Control-Request-Headers: %s",
                request.headers.get("Access-Control-Request-Headers"),
            )

    jwt_secret = os.getenv("JWT_SECRET_KEY")
    if not jwt_secret:
        if is_production:
            raise RuntimeError(
                "JWT_SECRET_KEY must be set in production. Refusing to start with a "
                "default/guessable signing key."
            )
        import secrets

        jwt_secret = secrets.token_urlsafe(32)
        app.logger.warning(
            "JWT_SECRET_KEY not set; using an ephemeral dev key (tokens will not survive a restart)"
        )
    app.config["JWT_SECRET_KEY"] = jwt_secret
    app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(seconds=43200)
    app.config["JWT_TOKEN_LOCATION"] = ["cookies"]
    app.config["JWT_COOKIE_SECURE"] = is_production
    app.config["JWT_COOKIE_SAMESITE"] = "Lax"
    app.config["JWT_COOKIE_CSRF_PROTECT"] = True
    app.config["JWT_SESSION_COOKIE"] = False
    app.config["JWT_ACCESS_COOKIE_PATH"] = "/"

    jwt = JWTManager(app)
    limiter.init_app(app)

    @jwt.invalid_token_loader
    def invalid_token_callback(error_string):
        app.logger.warning("Invalid token: %s", error_string)
        return jsonify(
            {
                "error": "Invalid or expired token. Please log in again.",
                "msg": error_string,
            }
        ), 401

    @jwt.expired_token_loader
    def expired_token_callback(jwt_header, jwt_payload):
        app.logger.info("Expired token used")
        return jsonify({"error": "Token has expired. Please log in again."}), 401

    @jwt.unauthorized_loader
    def missing_token_callback(error_string):
        app.logger.warning("Missing token: %s", error_string)
        return jsonify({"error": "Authorization token is required."}), 401

    @jwt.token_verification_failed_loader
    def token_verification_failed_callback(jwt_header, jwt_payload):
        app.logger.warning("Token verification failed")
        return jsonify({"error": "Token verification failed. Please log in again."}), 401

    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(portfolio_bp, url_prefix="/portfolio")

    @app.route("/health", methods=["GET"])
    def health_check():
        app.logger.info("[HEALTH] Health check called")

        health_status = {"status": "ok", "checks": {}}

        try:
            app.logger.info("[HEALTH] Testing database connection...")
            conn = get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1")
            conn.close()
            health_status["checks"]["database"] = "ok"
            app.logger.info("[HEALTH] Database connection successful")
        except Exception as exc:
            health_status["checks"]["database"] = (
                "error" if is_production else f"error: {str(exc)}"
            )
            health_status["status"] = "degraded"
            app.logger.error(
                "[HEALTH] Database connection failed: %s", str(exc), exc_info=True
            )

        if not is_production:
            health_status["environment"] = env
            health_status["debug"] = debug
            health_status["cors_origins"] = os.getenv("CORS_ORIGINS", "*")

        app.logger.info("[HEALTH] Health check result: %s", health_status)
        return health_status, 200 if health_status["status"] == "ok" else 503

    return app
