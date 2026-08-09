"""Postgres identity repositories."""

from algolens.domain.identity.models import user_from_row
from algolens.infrastructure.db.postgres import execute_query, get_db_connection


class PostgresUserRepository:
    def __init__(self, execute_query_func=None, connection_factory=None):
        self.execute_query = execute_query_func or execute_query
        self.connection_factory = connection_factory or get_db_connection

    def find_by_email(self, email):
        query = "SELECT * FROM auth.users WHERE email = %s"
        row = self.execute_query(query, (email,), fetch_one=True)
        return user_from_row(row) if row else None

    def find_by_id(self, user_id):
        query = "SELECT * FROM auth.users WHERE id = %s"
        row = self.execute_query(query, (user_id,), fetch_one=True)
        return user_from_row(row) if row else None

    def complete_registration(self, email, password_hash, first_name, last_name):
        update_query = """
            UPDATE auth.users
            SET password_hash = %s, first_name = %s, last_name = %s
            WHERE email = %s
            RETURNING id, email, first_name, last_name, role
        """

        conn = self.connection_factory()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    update_query, (password_hash, first_name, last_name, email)
                )
                updated_user = cursor.fetchone()
                conn.commit()
            return user_from_row(updated_user)
        finally:
            conn.close()
