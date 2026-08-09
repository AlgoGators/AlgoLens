"""Password hashing infrastructure."""

from werkzeug.security import check_password_hash, generate_password_hash


class WerkzeugPasswordHasher:
    def __init__(self, verify_func=None, hash_func=None):
        self.verify_func = verify_func or check_password_hash
        self.hash_func = hash_func or generate_password_hash

    def verify(self, password_hash, password):
        return self.verify_func(password_hash, password)

    def hash(self, password):
        return self.hash_func(password)
