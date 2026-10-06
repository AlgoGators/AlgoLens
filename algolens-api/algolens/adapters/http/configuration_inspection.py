"""Protected, read-only configuration inspection transport."""

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

from algolens.adapters.http.portfolio import ASSIGNMENT_MESSAGES, internal_only
from algolens.application.configuration_inspection import InspectionError
from algolens.domain.portfolio.portfolio_assignment import AssignmentValidationError
from algolens.infrastructure.config.dependencies import create_configuration_inspection_service
from algolens.adapters.http.capability_guard import requires_capability


configuration_inspection_bp = Blueprint("configuration_inspection", __name__)


@configuration_inspection_bp.after_request
def _no_store(response):
    response.headers["Cache-Control"] = "no-store"
    return response


@configuration_inspection_bp.route("/strategies/<registry_id>/configuration", methods=["GET"])
@requires_capability("view_internal")
@jwt_required()
@internal_only
def get_configuration_inspection(registry_id):
    try:
        response = create_configuration_inspection_service().inspect(
            registry_id, request.args.get("portfolio_id")
        )
        return jsonify(response), 200
    except AssignmentValidationError as exc:
        return jsonify({"error": ASSIGNMENT_MESSAGES.get(exc.code, "Invalid book"),
                        "code": exc.code}), 400
    except InspectionError as exc:
        if exc.status == 404:
            return jsonify({"error": "Strategy not found", "code": exc.code}), 404
        if exc.status == 400:
            return jsonify({"error": ASSIGNMENT_MESSAGES["not_a_member_of_book"],
                            "code": "not_a_member_of_book"}), 400
        return jsonify({"error": "Configuration inspection unavailable",
                        "code": "storage_unavailable"}), 503
    except Exception:
        return jsonify({"error": "Configuration inspection unavailable",
                        "code": "storage_unavailable"}), 503
