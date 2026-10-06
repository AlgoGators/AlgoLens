"""Non-disclosing HTTP access to an investor's published system book."""

from datetime import date
import re

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from algolens.adapters.http.portfolio import _current_user
from algolens.application.identity.use_cases import UserNotFound
from algolens.infrastructure.config.dependencies import create_investor_book_service
from algolens.adapters.http.capability_guard import disabled_route


investor_books_bp = Blueprint("investor_books", __name__)
_BOOK = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}")


def _service():
    return create_investor_book_service()


def _not_found():
    return jsonify({"error": "Not found"}), 404


@investor_books_bp.route("/investor/books/<portfolio_id>", methods=["GET"])
@disabled_route
@jwt_required()
def get_investor_book(portfolio_id):
    if _BOOK.fullmatch(portfolio_id) is None:
        return _not_found()
    source_day = request.args.get("date")
    if source_day is not None:
        try:
            parsed = date.fromisoformat(source_day)
        except ValueError:
            return jsonify({"error": "Invalid date", "code": "invalid_date"}), 400
        if parsed.isoformat() != source_day:
            return jsonify({"error": "Invalid date", "code": "invalid_date"}), 400
    try:
        user = _current_user()
    except UserNotFound:
        return _not_found()
    except Exception:
        current_app.logger.error("Investor identity lookup failed")
        return jsonify({"error": "Investor book unavailable"}), 503
    if user.role != "investor" and not str(user.role or "").startswith("subscriber_"):
        return _not_found()
    try:
        value = _service().read(str(get_jwt_identity()), portfolio_id, source_day)
    except Exception:
        current_app.logger.error("Investor book read failed", exc_info=True)
        return jsonify({"error": "Investor book unavailable"}), 503
    if value is None:
        return _not_found()
    response = jsonify(value)
    response.headers["Cache-Control"] = "private, no-store"
    return response, 200
