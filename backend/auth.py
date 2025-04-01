from flask import Blueprint, request, jsonify
from flask_jwt_extended import create_access_token
from sqlalchemy.exc import IntegrityError

from db_models import get_session, get_engine
from user_service import create_user, get_user_by_email, check_user_password

auth_bp = Blueprint("auth", __name__)
engine = get_engine()

@auth_bp.route("/register", methods=["POST"])
def register():
    valid_roles = {"general_member", "team_lead", "exec_board"}
    db = get_session(engine)
    data = request.get_json()
    email = data.get("email")
    password = data.get("password")
    role = data.get("role", "general_member")

    if not email or not password:
        return jsonify({"msg":"Email and password are required"}), 400
    
    if get_user_by_email(db, email):
        return jsonify({"msg": "User already exists"}), 400
    
    if role not in valid_roles:
        return jsonify({"msg": f"Invalid role '{role}'"}), 400

    try:
        user = create_user(db, email, password, role)
        return jsonify({"id": user.id, "email":user.email, "role": user.role}), 201
    except IntegrityError:
        return jsonify({"msg": "Error creating user"}), 500
    
@auth_bp.route("/login", methods=["POST"])
def login():
    db = get_session(engine)
    data = request.get_json()
    email = data.get("email")
    password = data.get("password")
    user = get_user_by_email(db, email)
    if not user or not user.check_password(password):
        return jsonify({"msg":"Incorrect email or password"}), 401
    access_token = create_access_token(identity=
        {"id": user.id,
        "email": user.email,
        "role": user.role})

    return jsonify(access_token=access_token), 200
        