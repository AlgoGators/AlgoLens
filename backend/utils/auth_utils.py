from functools import wraps
from flask_jwt_extended import get_jwt, get_jwt_identity
from flask import jsonify

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
            identity = get_jwt_identity()
            target_id = kwargs.get(param_name)

            if str(identity) == str(target_id):
                return fn(*args, **kwargs)

            if identity.get("role") in allowed_roles:
                return fn(*args, **kwargs)

            return jsonify({"msg": "Forbidden: not owner or authorized role"}), 403

        return wrapper
    return decorator