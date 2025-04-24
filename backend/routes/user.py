from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt
import secrets
import string

from db_models import get_session, get_engine
from services.user_service import get_user_by_id, update_user, delete_user, get_all_users, update_password
from utils.auth_utils import self_or_roles_required, roles_required, validate_password

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
    new_role = data.get("role")

    claims = get_jwt()
    # Only check role updates if role is being changed
    if new_role is not None and claims["role"] != "exec_board":
        return jsonify({"msg":"You cannot update your role."}), 401

    # For non-exec board members, ensure role cannot be changed
    if claims["role"] != "exec_board":
        new_role = None

    updated_user = update_user(db, user_id, role=new_role, first_name=new_first_name, last_name=new_last_name)

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

# Changes a user's password
@user_bp.route("/<int:user_id>/password", methods=["PATCH"])
@jwt_required()
@self_or_roles_required()
def update_password_route(user_id):
    db = get_session(engine)
    data = request.get_json()
    old_password = data.get("old_password")
    new_password = data.get("new_password")
    if not old_password:
        return jsonify({
            "msg": "Missing old password"
        }), 400
    
    if not new_password:
        return jsonify({
            "msg": "Missing new password"
        }), 400
    
    user = get_user_by_id(db, user_id)
    if not user:
        return jsonify({"msg": "User not found"}), 404
        
    if not user.check_password(old_password):
        return jsonify({"msg": "Old password did not match"}), 401
    
    # Validate new password
    is_valid, error_message = validate_password(new_password)
    if not is_valid:
        return jsonify({"msg": error_message}), 400
    
    user.set_password(new_password)
    user.force_password_change = False  # Clear the flag
    db.commit()

    return jsonify({
        "msg": "Password was successfully updated",
        "user": {
            "id": user.id,
            "email": user.email,
            "role": user.role,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "team": user.team,
            "force_password_change": False
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

def generate_random_password(length=12):
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return ''.join(secrets.choice(alphabet) for _ in range(length))

@user_bp.route("/<int:user_id>/admin-reset-password", methods=["POST"])
@jwt_required()
@roles_required("exec_board")
def admin_reset_password(user_id):
    db = get_session(engine)
    user = get_user_by_id(db, user_id)
    
    if not user:
        return jsonify({"msg": "User not found"}), 404
    
    # Generate random password
    new_password = generate_random_password()
    
    # Update user's password and set force_password_change flag
    user.set_password(new_password)
    user.force_password_change = True
    db.commit()
    
    return jsonify({
        "msg": "Password has been reset",
        "temp_password": new_password
    }), 200