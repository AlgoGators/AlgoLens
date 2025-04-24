from flask import Blueprint, request, jsonify
from datetime import timedelta

from db_models import get_session, get_engine
from services.auth_service import handle_register, handle_login, get_user_by_email
from utils.auth_utils import roles_required
from flask_jwt_extended import jwt_required, create_access_token

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

def handle_login(db, data):
    email = data.get("email")
    password = data.get("password")
    user = get_user_by_email(db, email)

    if not user:
        return jsonify({"msg": "User does not exist"}), 401
    
    if not user.check_password(password):
        return jsonify({"msg": "Incorrect password"}), 401

    access_token = create_access_token(
        identity=str(user.id),
        additional_claims={
            "email": user.email,
            "role": user.role,
            "force_password_change": user.force_password_change
        },
        expires_delta=timedelta(hours=12)
    )

    return jsonify({
        "access_token": access_token,
        "force_password_change": user.force_password_change
    }), 200
