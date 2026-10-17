"""Portfolio stream names produced by the trading engine."""

# The QT book and the model's book of the same portfolio (D-3). The model twin's "benchmark"
# stream is gone with the twin (D-1); the engine never wrote it.
PORTFOLIO_STREAMS = ("qt", "system")

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
