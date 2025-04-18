from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt

from db_models import get_session, get_engine
from services.user_service import get_user_by_id, update_user, delete_user, get_all_users
from utils.auth_utils import self_or_roles_required, roles_required

user_bp = Blueprint("user", __name__)
engine = get_engine()

# Updates a user
@user_bp.route("/<int:user_id>", methods=["PATCH"])
@jwt_required()
@self_or_roles_required("user_id", "exec_board")
def update_user_route(user_id):
    db = get_session(engine)
    data = request.get_json()
    new_first_name = data.get("first_name")
    new_last_name = data.get("last_name")
    new_password = data.get("password")
    new_role = data.get("role")

    claims = get_jwt()
    if claims["role"] != "exec_board":
        new_role = None
        return jsonify({"msg":"You cannot update your role."}), 401

    updated_user = update_user(db, user_id, password=new_password, role=new_role, first_name=new_first_name, last_name=new_last_name)

    if not updated_user:
        return jsonify({"msg": "User not found"}), 404

    return jsonify({
        "msg": "User updated",
        "user": {
            "id": updated_user.id,
            "first_name": updated_user.first_name,
            "last_name": updated_user.last_name,
            "email": updated_user.email,
            "role": updated_user.role
        }
    }), 200


# Returns a user's information given an ID
@user_bp.route("/<int:user_id>", methods=["GET"])
@jwt_required()
@self_or_roles_required("user_id", "exec_board")
def get_user_route(user_id):
    db = get_session(engine)
    user = get_user_by_id(db, user_id)
    if not user:
        return jsonify({"msg": "User not found"}), 404

    return jsonify({
        "msg": "Success",
        "user": {
            "id": user.id,
            "email": user.email,
            "role": user.role,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "team": user.team
        }
    }), 200

@user_bp.route("/<int:user_id>", methods=["DELETE"])
@jwt_required()
@self_or_roles_required("user_id", "exec_board")
def delete_user_route(user_id):
    db = get_session(engine)    
    if delete_user(db, user_id):
        return jsonify({"msg":"User has been deleted."}), 200
    else:
        return jsonify({"msg": "User not found"}), 404

@user_bp.route("/", methods=["GET"])
@jwt_required()
@roles_required("exec_board")
def get_all():
    db = get_session(engine)
    users = get_all_users(db)
    return jsonify({
        "users":[{
            "id": user.id,
            "email": user.email,
            "role": user.role,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "team": user.team
        } for user in users]
    }), 200