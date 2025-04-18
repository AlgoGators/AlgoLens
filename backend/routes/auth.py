from flask import Blueprint, request

from db_models import get_session, get_engine
from services.auth_service import handle_register, handle_login
from utils.auth_utils import roles_required
from flask_jwt_extended import jwt_required

auth_bp = Blueprint("auth", __name__)
engine = get_engine()

@auth_bp.route("/register", methods=["POST"])
@jwt_required()
@roles_required("exec_board")
def register():
    db = get_session(engine)
    data = request.get_json()
    return handle_register(db, data)

@auth_bp.route("/login", methods=["POST"])
def login():
    db = get_session(engine)
    data = request.get_json()
    return handle_login(db, data)
