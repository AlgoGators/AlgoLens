"""Flask application composition."""

import logging
import os
import re
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
from algolens.adapters.http.qt_workflow import qt_workflow_bp
from algolens.adapters.http.runtime_control import runtime_control_bp
from algolens.adapters.http.configuration_inspection import configuration_inspection_bp
from algolens.adapters.http.investor_books import investor_books_bp
from algolens.infrastructure.db.postgres import get_db_connection
from algolens.infrastructure.config.production_readiness import (
    ReadinessResult,
    ReadinessSnapshotCache,
    evaluator_isolation_probe,
    evaluate_readiness,
    load_runtime_contract,
    runtime_configuration_file_probe,
)
from extensions import limiter

ENV_PATH = Path(__file__).resolve().parents[3] / ".env"


def create_app():
    load_dotenv(dotenv_path=ENV_PATH)

    env = os.getenv("FLASK_ENV", "production")
    debug = os.getenv("FLASK_DEBUG", "False").lower() == "true"
    is_production = env == "production"
    production_contract = load_runtime_contract() if is_production else None
    readiness_cache = ReadinessSnapshotCache(5.0)

    app = Flask(__name__)
    app.config["ALGOLENS_ENV"] = env
    app.config["ALGOLENS_DEBUG"] = debug
    app.config["ALGOLENS_IS_PRODUCTION"] = is_production
    app.config["PRODUCTION_RUNTIME_CONTRACT"] = production_contract

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
        data = request.get_json(silent=True)
        if isinstance(data, dict):
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
    app.register_blueprint(qt_workflow_bp, url_prefix="/portfolio")
    app.config['QT_EVALUATOR_BUNDLE_DIR'] = os.getenv('QT_EVALUATOR_BUNDLE_DIR') or None
    app.register_blueprint(runtime_control_bp, url_prefix="/portfolio")
    app.register_blueprint(configuration_inspection_bp, url_prefix="/portfolio")
    app.register_blueprint(investor_books_bp, url_prefix="/portfolio")

    release_sha = os.getenv("APP_RELEASE_SHA", "")
    release_sha = release_sha.lower() if re.fullmatch(r"[0-9a-fA-F]{40}", release_sha) else None

    @app.route("/version", methods=["GET"])
    def version():
        # Release identity is public and independent of database readiness.
        response = jsonify({"release": release_sha})
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.route("/health", methods=["GET"])
    def health_check():
        return {"status": "ok", "checks": {"process": "ok"}}, 200

    @app.route("/ready", methods=["GET"])
    def readiness_check():
        try:
            checker = app.config.get("PRODUCTION_READINESS_CHECKER")
            if checker is not None:
                result = checker()
            elif production_contract is None:
                result = ReadinessResult(
                    {"configuration": "error"},
                    ("production_runtime_not_configured",),
                    {"schema": "algolens-readiness-evidence/v1", "status": "not_ready"},
                )
            else:
                result = readiness_cache.get(
                    lambda: evaluate_readiness(
                        production_contract,
                        connection_factory=get_db_connection,
                        schema_probe=app.config.get("QT_SCHEMA_READINESS_PROBE"),
                        role_probe=app.config.get("QT_ROLE_READINESS_PROBE"),
                        runtime_configuration_probe=runtime_configuration_file_probe,
                        evaluator_probe=app.config.get(
                            "QT_EVALUATOR_READINESS_PROBE", evaluator_isolation_probe
                        ),
                        capability_probe=app.config.get("QT_CAPABILITY_READINESS_PROBE"),
                        worker_probe=app.config.get("QT_WORKER_READINESS_PROBE"),
                    )
                )
        except Exception:
            app.logger.error("Production readiness check failed")
            result = ReadinessResult(
                {"configuration": "error"},
                ("production_readiness_failed",),
                {"schema": "algolens-readiness-evidence/v1", "status": "not_ready"},
            )
        return (
            result.public_payload(),
            200 if result.ready else 503,
            {"Cache-Control": "no-store"},
        )

    # T1 owns the default-deny route guard.  Install it only after every
    # blueprint and application route is registered so its route inventory is
    # complete.  This lane can still be tested before T1 is integrated; in
    # that state the capability readiness probe remains fail-closed.
    try:
        from algolens.adapters.http.capability_guard import install_capability_guard
    except ModuleNotFoundError as error:
        if error.name != "algolens.adapters.http.capability_guard":
            raise
        app.config["CAPABILITY_GUARD_INSTALLED"] = False
    else:
        install_capability_guard(
            app,
            explicitly_open_endpoints={"version", "health_check", "readiness_check"},
        )
        app.config["CAPABILITY_GUARD_INSTALLED"] = True

    return app
