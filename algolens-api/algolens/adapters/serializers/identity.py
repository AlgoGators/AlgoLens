"""Identity HTTP serializers."""


def serialize_user(user):
    return {
        "id": user.id,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "role": user.role,
    }


def serialize_user_session(user):
    return {"user": serialize_user(user)}


def serialize_check_email(result):
    payload = {"exists": result.exists, "message": result.message}
    if result.exists:
        payload["registered"] = result.registered
    return payload
