"""JWT cookie session infrastructure."""

from flask_jwt_extended import create_access_token, set_access_cookies, unset_jwt_cookies


class FlaskJwtSessionIssuer:
    def create_token(self, user):
        return create_access_token(
            identity=str(user.id),
            additional_claims={"email": user.email, "role": user.role},
        )

    def set_access_cookie(self, response, access_token):
        set_access_cookies(response, access_token)

    def clear_cookies(self, response):
        unset_jwt_cookies(response)
