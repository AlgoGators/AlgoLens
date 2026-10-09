"""Portfolio stream names produced by the trading engine."""

PORTFOLIO_STREAMS = ("qt", "system", "benchmark")

# Headline dashboard values represent the real book.
PRIMARY_STREAM = "qt"

# Position books (trading.positions.portfolio_type) a reader may ask for:
#   system       trade-ngin's own signal-driven output
#   qt_proposal  what QT proposes before it is accepted
#   qt           what QT actually holds -- the real book
POSITION_BOOKS = ("system", "qt_proposal", "qt")

# AlgoLens opens on the real book. Until qt rows exist for a portfolio, a
# request that did not name a book is served the system book instead, and the
# response says so.
DEFAULT_BOOK = PRIMARY_STREAM
FALLBACK_BOOK = "system"
