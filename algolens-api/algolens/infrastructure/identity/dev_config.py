"""Environment-backed dev-login settings."""

import os


class EnvironmentDevAuthConfig:
    def is_enabled(self):
        if os.getenv("FLASK_ENV", "production").lower() == "production":
            return False
        return os.getenv("DEV_MODE") == "1"

    def user_id(self):
        return int(os.getenv("DEV_USER_ID", "1"))

    def user_email(self):
        return os.getenv("DEV_USER_EMAIL", "dev@algolens.local")

    def user_role(self):
        return os.getenv("DEV_USER_ROLE", "admin")
