"""Screen access, admin and investor HTTP routes, mounted under /api.

  GET   /api/me/screens                    the signed-in user's screens
  GET   /api/admin/users                   every user with their screens (admin)
  PUT   /api/admin/users/<id>/screens      replace a user's screens (admin)
  GET   /api/admin/reports                 every report, published or not (admin)
  POST  /api/admin/reports                 upload a PDF report or letter (admin)
  PATCH /api/admin/reports/<id>            rename or (un)publish a report (admin)
  GET   /api/admin/reports/<id>/download   any report's PDF (admin)
  GET   /api/investor/allocation           the published qt book (investor)
  GET   /api/investor/reports              published reports (investor)
  GET   /api/investor/reports/<id>/download

Admin is the exec_board role (exec equals admin). Screens are assigned per
user by an admin (Dom, 2026-10-11); see algolens.domain.identity.screens.
"""

from functools import wraps

import psycopg2
from flask import Blueprint, Response, current_app, jsonify, request
from flask_jwt_extended import get_jwt, get_jwt_identity, jwt_required

from algolens.adapters.http.access import (
    admin_only,
    current_is_admin,
    current_screens,
    requires_screen,
)
from algolens.application.identity.screen_access import (
    ListUsersWithScreens,
    ScreenAccessUnavailable,
    ScreenUserNotFound,
    SetUserScreens,
)
from algolens.application.investor.use_cases import (
    GetInvestorPortfolio,
    GetReportFile,
    LinkNotStored,
    ListInvestorLinks,
    ListReports,
    ReportNotFound,
    SetInvestorLink,
    UpdateReport,
    UploadReport,
)
from algolens.application.shared.errors import ValidationError
from algolens.domain.identity.screens import INVESTOR, ScreenRuleError
from algolens.domain.investor.reports import MAX_REPORT_BYTES, ReportRuleError
from algolens.infrastructure.config.dependencies import (
    create_investor_dependencies,
    create_screen_access_dependencies,
)
from extensions import limiter

api_bp = Blueprint("api", __name__)

_ERRORS = (
    (ScreenRuleError, 400),
    (ReportRuleError, 400),
    (LinkNotStored, 409),
    (ValidationError, 400),
    (ScreenUserNotFound, 404),
    (ReportNotFound, 404),
    (ScreenAccessUnavailable, 503),
)


def handled(fn):
    """Map the rule errors to their HTTP status; anything else is a logged 500."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except tuple(e for e, _ in _ERRORS) as exc:
            status = next(code for error, code in _ERRORS if isinstance(exc, error))
            if isinstance(exc, ScreenAccessUnavailable):
                return jsonify({"error": "Screen access is not set up yet (migration 003)"}), status
            return jsonify({"error": str(exc)}), status
        except psycopg2.errors.UndefinedTable as exc:
            current_app.logger.error("[API] %s: table missing: %s", request.path, exc)
            return jsonify({"error": "This feature is not set up yet (migration 003)"}), 503
        except Exception as exc:
            current_app.logger.error("[API] %s failed: %s", request.path, exc, exc_info=True)
            return jsonify({"error": "The request failed"}), 500

    return wrapper


def _admin_email():
    return (get_jwt().get("email") or "").strip().lower() or "unknown"


def _iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


def _report(row):
    return {
        "id": row["id"],
        "title": row["title"],
        "kind": row["kind"],
        "period_label": row.get("period_label"),
        "filename": row["filename"],
        "size_bytes": row["size_bytes"],
        "uploaded_by": row.get("uploaded_by"),
        "uploaded_at": _iso(row.get("uploaded_at")),
        "published": bool(row.get("published")),
    }


def _user(row):
    return {
        "id": row["id"],
        "email": row["email"],
        "first_name": row.get("first_name"),
        "last_name": row.get("last_name"),
        "role": row.get("role"),
        "screens": row.get("screens") or [],
    }


# --- me -----------------------------------------------------------------------


@api_bp.route("/me/screens", methods=["GET"])
@jwt_required()
@handled
def my_screens():
    return jsonify({"screens": current_screens(), "is_admin": current_is_admin()}), 200


# --- admin: screen access -----------------------------------------------------


@api_bp.route("/admin/users", methods=["GET"])
@jwt_required()
@admin_only
@handled
def admin_users():
    users = ListUsersWithScreens(create_screen_access_dependencies()).execute()
    return jsonify({"users": [_user(u) for u in users]}), 200


@api_bp.route("/admin/users/<int:user_id>/screens", methods=["PUT"])
@jwt_required()
@admin_only
@limiter.limit("60 per minute")
@handled
def admin_set_screens(user_id):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or "screens" not in payload:
        return jsonify({"error": "Request body must be a JSON object with 'screens'"}), 400
    by = _admin_email()
    screens, granted, revoked = SetUserScreens(create_screen_access_dependencies()).execute(
        user_id, payload["screens"], by
    )
    current_app.logger.info(
        "[ACCESS] %s set user %s screens to %s (granted %s, revoked %s)",
        by,
        user_id,
        screens,
        list(granted),
        list(revoked),
    )
    return jsonify(
        {"id": user_id, "screens": screens, "granted": list(granted), "revoked": list(revoked)}
    ), 200


# --- admin: reports -----------------------------------------------------------


@api_bp.route("/admin/reports", methods=["GET"])
@jwt_required()
@admin_only
@handled
def admin_reports():
    _registry, repo = create_investor_dependencies()
    reports = ListReports(repo).execute(published_only=False)
    return jsonify({"reports": [_report(r) for r in reports]}), 200


@api_bp.route("/admin/reports", methods=["POST"])
@jwt_required()
@admin_only
@limiter.limit("20 per minute")
@handled
def admin_upload_report():
    if request.content_length and request.content_length > MAX_REPORT_BYTES + 64 * 1024:
        return jsonify({"error": "The file is larger than 10 MB"}), 413
    upload = request.files.get("file")
    if upload is None:
        return jsonify({"error": "Attach the PDF as 'file'"}), 400
    data = upload.read(MAX_REPORT_BYTES + 1)
    _registry, repo = create_investor_dependencies()
    report = UploadReport(repo).execute(
        title=request.form.get("title"),
        kind=request.form.get("kind"),
        period_label=request.form.get("period_label"),
        filename=upload.filename,
        data=data,
        uploaded_by=_admin_email(),
    )
    current_app.logger.info(
        "[REPORTS] %s uploaded report %s (%s bytes)", _admin_email(), report["id"], report["size_bytes"]
    )
    return jsonify(_report(report)), 201


@api_bp.route("/admin/reports/<int:report_id>", methods=["PATCH"])
@jwt_required()
@admin_only
@handled
def admin_update_report(report_id):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Request body must be a JSON object"}), 400
    _registry, repo = create_investor_dependencies()
    report = UpdateReport(repo).execute(report_id, payload)
    current_app.logger.info("[REPORTS] %s updated report %s: %s", _admin_email(), report_id, payload)
    return jsonify(_report(report)), 200


# --- investor -----------------------------------------------------------------


@api_bp.route("/investor/allocation", methods=["GET"])
@jwt_required()
@requires_screen(INVESTOR)
@handled
def investor_allocation():
    # D-25: only the portfolio and book this investor follows (the QT book by default).
    registry, repo = create_investor_dependencies()
    portfolios = GetInvestorPortfolio(registry, repo).execute(get_jwt_identity())
    return jsonify({"portfolios": portfolios}), 200


@api_bp.route("/admin/investor-links", methods=["GET"])
@jwt_required()
@admin_only
@handled
def admin_investor_links():
    registry, repo = create_investor_dependencies()
    return jsonify(ListInvestorLinks(registry, repo).execute()), 200


@api_bp.route("/admin/investors/<int:user_id>/portfolio", methods=["PUT"])
@jwt_required()
@admin_only
@handled
def admin_set_investor_link(user_id):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Request body must be a JSON object"}), 400
    registry, repo = create_investor_dependencies()
    choice = SetInvestorLink(registry, repo).execute(
        user_id, payload.get("portfolio_id"), payload.get("book"), _admin_email()
    )
    current_app.logger.info("[INVESTOR] %s set user %s to follow %s", _admin_email(), user_id, choice["label"])
    return jsonify(choice), 200


@api_bp.route("/investor/reports", methods=["GET"])
@jwt_required()
@requires_screen(INVESTOR)
@handled
def investor_reports():
    _registry, repo = create_investor_dependencies()
    return jsonify({"reports": [_report(r) for r in ListReports(repo).execute()]}), 200


def _pdf_response(report):
    content = report["content"]
    body = bytes(content) if not isinstance(content, bytes) else content
    response = Response(body, mimetype="application/pdf")
    response.headers["Content-Disposition"] = f'attachment; filename="{report["filename"]}"'
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "private, no-store"
    return response


@api_bp.route("/investor/reports/<int:report_id>/download", methods=["GET"])
@jwt_required()
@requires_screen(INVESTOR)
@handled
def investor_report_download(report_id):
    _registry, repo = create_investor_dependencies()
    return _pdf_response(GetReportFile(repo).execute(report_id))


@api_bp.route("/admin/reports/<int:report_id>/download", methods=["GET"])
@jwt_required()
@admin_only
@handled
def admin_report_download(report_id):
    _registry, repo = create_investor_dependencies()
    return _pdf_response(GetReportFile(repo).execute(report_id, published_only=False))
