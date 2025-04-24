from functools import wraps
from flask_jwt_extended import get_jwt, get_jwt_identity
from flask import jsonify

from password_validator import PasswordValidator

# Create a schema
password_schema = PasswordValidator()

# Define rules
password_schema \
    .min(8) \
    .max(100) \
    .has().uppercase() \
    .has().lowercase() \
    .has().digits() \
    .has().symbols() \
    .has().no().spaces()

def roles_required(*allowed_roles):
    """
    Custom decorator to restrict access to users with specific roles.
    Usage: @roles_required("exec_board", "team_lead")
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            claims = get_jwt()
            print(claims.get("role"))
            if claims.get("role") not in allowed_roles:
                return jsonify({"msg": "Forbidden: insufficient role"}), 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator

def self_or_roles_required(param_name="user_id", *allowed_roles):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            identity = get_jwt_identity()  # This is just the user ID
            claims = get_jwt()  # This contains the role
            target_id = kwargs.get(param_name)

            # Check if user is accessing their own data
            if str(identity) == str(target_id):
                return fn(*args, **kwargs)

            # Check if user has required role
            if claims.get("role") in allowed_roles:  # Use claims instead of identity
                return fn(*args, **kwargs)

            return jsonify({"msg": "Forbidden: not owner or authorized role"}), 403

        return wrapper
    return decorator

def validate_password(password: str) -> tuple[bool, str]:
    """
    Validates a password against the defined schema
    Returns: (is_valid: bool, error_message: str)
    """
    # Check each rule individually to provide detailed feedback
    if len(password) < 8:
        return False, "Password must be at least 8 characters long"
    if len(password) > 100:
        return False, "Password must be less than 100 characters"
    if not any(c.isupper() for c in password):
        return False, "Password must contain at least one uppercase letter"
    if not any(c.islower() for c in password):
        return False, "Password must contain at least one lowercase letter"
    if not any(c.isdigit() for c in password):
        return False, "Password must contain at least one number"
    if not any(not c.isalnum() for c in password):
        return False, "Password must contain at least one special character"
    if ' ' in password:
        return False, "Password cannot contain spaces"
    
    return True, ""