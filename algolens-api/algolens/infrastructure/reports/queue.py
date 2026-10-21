"""reports.report_queue (migration 006) over Postgres."""

from algolens.application.reports.ports import QueuedReport, ReportQueue
from algolens.infrastructure.db.postgres import get_db_connection


class PostgresReportQueue(ReportQueue):
    def __init__(self, connection_factory=None):
        self.connection_factory = connection_factory or get_db_connection

    def claim_next(self):
        """SKIP LOCKED, so two workers never take the same row."""
        conn = self.connection_factory()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE reports.report_queue q
                       SET status = 'sending', claimed_at = now(), attempts = q.attempts + 1
                     WHERE q.id = (
                         SELECT id FROM reports.report_queue
                          WHERE ((status = 'queued'
                                  OR (status = 'failed' AND attempts < max_attempts)
                                  -- a worker that died mid-send: take the row back
                                  OR (status = 'sending' AND claimed_at < now() - interval '15 minutes'))
                                 AND attempts < max_attempts)
                          ORDER BY created_at
                          FOR UPDATE SKIP LOCKED
                          LIMIT 1)
                    RETURNING q.id, q.report_type, q.portfolio_id, q.recipients, q.payload, q.attempts
                    """
                )
                row = cursor.fetchone()
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        if row is None:
            return None
        return QueuedReport(id=row["id"], report_type=row["report_type"],
                            portfolio_id=row["portfolio_id"], recipients=tuple(row["recipients"]),
                            payload=row["payload"], attempts=row["attempts"])

    def _finish(self, sql, params):
        conn = self.connection_factory()
        try:
            with conn.cursor() as cursor:
                cursor.execute(sql, params)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def mark_sent(self, report_id):
        self._finish(
            "UPDATE reports.report_queue SET status = 'sent', sent_at = now(), last_error = NULL "
            "WHERE id = %s", (report_id,))

    def mark_failed(self, report_id, error):
        self._finish(
            "UPDATE reports.report_queue SET status = 'failed', last_error = %s WHERE id = %s",
            (error[:2000], report_id))
