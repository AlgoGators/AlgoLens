from flask import jsonify
from flask_jwt_extended import create_access_token
from sqlalchemy.exc import IntegrityError
from datetime import timedelta
from utils.auth_utils import validate_password


from services.user_service import create_user, get_user_by_email


def handle_register(db, data):
    required_fields = ["email", "password", "first_name", "last_name", "team"]
    missing_fields = [field for field in required_fields if not data.get(field)]

    if missing_fields:
        return jsonify({
            "msg": f"Missing required field(s): {', '.join(missing_fields)}"
        }), 400

    email = data["email"]
    password = data["password"]
    first_name = data["first_name"]
    last_name = data["last_name"]
    team = data.get("team")
    role = data.get("role", "general_member")

    valid_roles = {"general_member", "team_lead", "exec_board"}

    if get_user_by_email(db, email):
        return jsonify({"msg": "User already exists"}), 400

    if role not in valid_roles:
        return jsonify({"msg": f"Invalid role '{role}'"}), 400
    
    # Validate password
    is_valid, error_message = validate_password(password)
    if not is_valid:
        return jsonify({"msg": error_message}), 400

    try:
        user = create_user(
            db,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
            team=team,
            role=role
        )
        return jsonify({
            "id": user.id,
            "email": user.email,
            "role": user.role,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "team": user.team
        }), 201

    except IntegrityError as e:
        return jsonify({"msg": "Database error during registration"}), 500


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
