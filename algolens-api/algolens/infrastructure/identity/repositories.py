"""Postgres identity repositories."""

from algolens.domain.identity.models import user_from_row
from algolens.infrastructure.db.postgres import execute_query, get_db_connection


class PostgresUserRepository:
    def __init__(self, execute_query_func=None, connection_factory=None):
        self.execute_query = execute_query_func or execute_query
        self.connection_factory = connection_factory or get_db_connection

    def find_by_email(self, email):
        query = """
            SELECT u.*
            FROM auth.users u
            WHERE lower(btrim(u.email)) = lower(btrim(%s))
              AND NOT EXISTS (
                  SELECT 1 FROM auth.account_retirements r
                  WHERE r.user_id = u.id
              )
              AND 1 = (
                  SELECT count(*) FROM auth.users candidate
                  WHERE lower(btrim(candidate.email)) = lower(btrim(%s))
                    AND NOT EXISTS (
                        SELECT 1 FROM auth.account_retirements r
                        WHERE r.user_id = candidate.id
                    )
              )
        """
        row = self.execute_query(query, (email, email), fetch_one=True)
        return user_from_row(row) if row else None

    def find_by_id(self, user_id):
        query = """
            SELECT u.* FROM auth.users u
            WHERE u.id = %s
              AND NOT EXISTS (
                  SELECT 1 FROM auth.account_retirements r
                  WHERE r.user_id = u.id
              )
        """
        row = self.execute_query(query, (user_id,), fetch_one=True)
        return user_from_row(row) if row else None

    def complete_registration(self, email, password_hash, first_name, last_name):
        update_query = """
            WITH candidates AS (
                SELECT u.id
                FROM auth.users u
                WHERE lower(btrim(u.email)) = lower(btrim(%s))
                  AND NOT EXISTS (
                      SELECT 1 FROM auth.account_retirements r
                      WHERE r.user_id = u.id
                  )
            ), eligible AS (
                SELECT min(id) AS id FROM candidates HAVING count(*) = 1
            )
            UPDATE auth.users u
            SET password_hash = %s, first_name = %s, last_name = %s
            FROM eligible e
            WHERE u.id = e.id
            RETURNING u.id, u.email, u.first_name, u.last_name, u.role
        """

        conn = self.connection_factory()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    update_query, (email, password_hash, first_name, last_name)
                )
                updated_user = cursor.fetchone()
                conn.commit()
            return user_from_row(updated_user) if updated_user else None
        finally:
            conn.close()
