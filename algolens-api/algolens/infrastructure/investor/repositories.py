"""Postgres reads for the investor screen, and investor.reports (migration 003)."""

from algolens.domain.investor.allocation import InstrumentInfo, parse_contract_size
from algolens.infrastructure.db.postgres import get_db_connection

_REPORT_COLUMNS = (
    "id, title, kind, period_label, filename, content_type, size_bytes, sha256, "
    "uploaded_by, uploaded_at, published"
)


class PostgresInvestorRepository:
    def __init__(self, connection_factory=None):
        self.connection_factory = connection_factory or get_db_connection

    def _read(self, sql, params=(), one=False):
        conn = self.connection_factory()
        try:
            with conn.cursor() as cursor:
                cursor.execute(sql, params)
                return cursor.fetchone() if one else cursor.fetchall()
        finally:
            conn.close()

    def _write(self, sql, params):
        conn = self.connection_factory()
        try:
            with conn.cursor() as cursor:
                cursor.execute(sql, params)
                row = cursor.fetchone()
            conn.commit()
            return row
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # --- allocation ----------------------------------------------------------

    def latest_published_day(self, portfolio_id):
        row = self._read(
            """
            SELECT max(date) AS day FROM trading.live_run_metadata
            WHERE portfolio_id = %s AND published_at IS NOT NULL
            """,
            (portfolio_id,),
            one=True,
        )
        return row["day"] if row else None

    def book_rows(self, portfolio_id, day, book):
        return self._read(
            """
            SELECT symbol,
                   SUM(quantity) AS quantity,
                   CASE WHEN SUM(quantity) <> 0
                        THEN SUM(quantity * average_price) / SUM(quantity)
                        ELSE MAX(average_price) END AS average_price
            FROM trading.positions
            WHERE portfolio_id = %s AND date = %s AND portfolio_type = %s
            GROUP BY symbol
            HAVING SUM(quantity) <> 0
            ORDER BY symbol
            """,
            (portfolio_id, day, book),
        )

    def instruments(self, roots):
        if not roots:
            return {}
        rows = self._read(
            """
            SELECT DISTINCT ON (cm."Databento Symbol")
                   cm."Databento Symbol" AS root, cm."Name" AS name,
                   cm."Sector" AS sector, cm."Contract Size" AS contract_size
            FROM metadata.contract_metadata cm
            WHERE cm."Databento Symbol" = ANY(%s)
            ORDER BY cm."Databento Symbol"
            """,
            (list(roots),),
        )
        return {
            row["root"]: InstrumentInfo(
                name=row["name"],
                sector=(row["sector"] or "").strip() or None,
                contract_size=parse_contract_size(row["contract_size"]),
            )
            for row in rows
        }

    # --- reports -------------------------------------------------------------

    def list_reports(self, published_only):
        where = "WHERE published" if published_only else ""
        return [
            dict(row)
            for row in self._read(
                f"SELECT {_REPORT_COLUMNS} FROM investor.reports {where} "
                "ORDER BY uploaded_at DESC, id DESC"
            )
        ]

    def get_report(self, report_id, published_only):
        where = "AND published" if published_only else ""
        row = self._read(
            f"SELECT {_REPORT_COLUMNS}, content FROM investor.reports WHERE id = %s {where}",
            (int(report_id),),
            one=True,
        )
        return dict(row) if row else None

    def insert_report(self, row, uploaded_by):
        import psycopg2

        return dict(
            self._write(
                f"""
                INSERT INTO investor.reports
                    (title, kind, period_label, filename, content_type, size_bytes,
                     sha256, content, uploaded_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING {_REPORT_COLUMNS}
                """,
                (
                    row["title"],
                    row["kind"],
                    row["period_label"],
                    row["filename"],
                    row["content_type"],
                    row["size_bytes"],
                    row["sha256"],
                    psycopg2.Binary(row["content"]),
                    uploaded_by,
                ),
            )
        )

    def update_report(self, report_id, changes):
        allowed = [key for key in ("title", "published") if key in changes]
        if not allowed:
            return None
        assignments = ", ".join(f"{key} = %s" for key in allowed)
        row = self._write(
            f"UPDATE investor.reports SET {assignments} WHERE id = %s RETURNING {_REPORT_COLUMNS}",
            tuple(changes[key] for key in allowed) + (int(report_id),),
        )
        return dict(row) if row else None
