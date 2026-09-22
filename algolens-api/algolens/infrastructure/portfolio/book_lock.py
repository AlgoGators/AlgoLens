"""Shared PostgreSQL lock for mutations that change a QT book's meaning."""


def acquire_qt_book_locks(cursor, *portfolio_ids):
    """Hold canonical book locks until the surrounding transaction finishes.

    Sorting is part of the contract: operations touching two books must acquire
    the same keys in the same order, regardless of their source/destination
    direction. Hash collisions only serialize unrelated books; they cannot let
    two mutations of the same book proceed concurrently.
    """
    books = sorted(
        {
            str(portfolio_id).strip().upper()
            for portfolio_id in portfolio_ids
            if portfolio_id is not None and str(portfolio_id).strip()
        }
    )
    for portfolio_id in books:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"algolens:qt-book:{portfolio_id}",),
        )
