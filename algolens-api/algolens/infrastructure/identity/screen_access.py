"""Postgres screen-access repository (auth.user_screen_access, migration 003)."""

import psycopg2

from algolens.application.identity.screen_access import ScreenAccessUnavailable
from algolens.domain.identity.screens import grant_changes
from algolens.infrastructure.db.postgres import get_db_connection


class PostgresScreenAccessRepository:
    def __init__(self, connection_factory=None):
        self.connection_factory = connection_factory or get_db_connection

    def screens_for(self, user_id):
        conn = self.connection_factory()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT screen FROM auth.user_screen_access WHERE user_id = %s",
                    (int(user_id),),
                )
                return [row["screen"] for row in cursor.fetchall()]
        except psycopg2.errors.UndefinedTable as exc:
            raise ScreenAccessUnavailable(str(exc)) from exc
        finally:
            conn.close()

    def list_users(self):
        conn = self.connection_factory()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT u.id, u.email, u.first_name, u.last_name, u.role::text AS role,
                           COALESCE(array_agg(a.screen ORDER BY a.screen)
                                    FILTER (WHERE a.screen IS NOT NULL), '{}') AS screens
                    FROM auth.users u
                    LEFT JOIN auth.user_screen_access a ON a.user_id = u.id
                    GROUP BY u.id
                    ORDER BY lower(u.email)
                    """
                )
                return [dict(row) for row in cursor.fetchall()]
        except psycopg2.errors.UndefinedTable as exc:
            raise ScreenAccessUnavailable(str(exc)) from exc
        finally:
            conn.close()

    def set_screens(self, user_id, screens, by_email):
        user_id = int(user_id)
        conn = self.connection_factory()
        try:
            with conn.cursor() as cursor:
                # Lock the user row: two admins saving the same user serialise,
                # and each logs only the changes it actually made.
                cursor.execute(
                    "SELECT id FROM auth.users WHERE id = %s FOR UPDATE", (user_id,)
                )
                if cursor.fetchone() is None:
                    conn.rollback()
                    return None
                cursor.execute(
                    "SELECT screen FROM auth.user_screen_access WHERE user_id = %s",
                    (user_id,),
                )
                current = [row["screen"] for row in cursor.fetchall()]
                granted, revoked = grant_changes(current, screens)
                for screen in granted:
                    cursor.execute(
                        """
                        INSERT INTO auth.user_screen_access (user_id, screen, granted_by)
                        VALUES (%s, %s, %s)
                        """,
                        (user_id, screen, by_email),
                    )
                if revoked:
                    cursor.execute(
                        """
                        DELETE FROM auth.user_screen_access
                        WHERE user_id = %s AND screen = ANY(%s)
                        """,
                        (user_id, list(revoked)),
                    )
                for action, changed in (("grant", granted), ("revoke", revoked)):
                    for screen in changed:
                        cursor.execute(
                            """
                            INSERT INTO auth.screen_access_log (user_id, screen, action, by_email)
                            VALUES (%s, %s, %s, %s)
                            """,
                            (user_id, screen, action, by_email),
                        )
            conn.commit()
            return list(screens), granted, revoked
        except psycopg2.errors.UndefinedTable as exc:
            conn.rollback()
            raise ScreenAccessUnavailable(str(exc)) from exc
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
