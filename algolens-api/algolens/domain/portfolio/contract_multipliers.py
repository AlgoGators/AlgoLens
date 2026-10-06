"""Contract size and price multiplier, which are not the same number.

WHY THIS EXISTS
---------------
AlgoLens reads ``"Contract Size"`` from ``metadata.contract_metadata`` and
multiplies ``quantity x price`` by it. That is right only for contracts whose
price is quoted in the underlying's own unit -- crude in dollars per barrel on
1,000 barrels, gold in dollars per ounce on 100 ounces. For those, the contract
size and the price multiplier are the same number and the confusion never
surfaces.

It surfaces where the quote convention differs, and there it is a clean factor
of 100:

  Treasuries  quote as a PERCENTAGE OF PAR. ZN at 110.5 is 110.5% of $100,000
              of face value. One point is $1,000, not $100,000.
  Grains      quote in CENTS per bushel. ZC at 450 is $4.50 a bushel on 5,000
              bushels. One point -- one cent -- is $50, not $5,000.
  Livestock,  quote in CENTS per pound. LE at 185.5 is $1.855 a pound on 40,000
  soybean oil pounds. One point is $400, not $40,000.

Seeded from trade-ngin's old fallback table, forty ZN came to $449,400,000 of
exposure against a $264,000 book. That is what this looks like on a screen.

WHICH CONVENTION THE COLUMN HOLDS IS NOT SETTLED
------------------------------------------------
The column is spelled "Contract Size", which says underlying units. The demo
seed holds point values, because seeding it with contract sizes produced the
figure above. A production database may hold either, and this module does not
have to know: it recognises both, because for each symbol it knows what each
reading would be.

This mirrors ``trade_ngin::resolve_price_multiplier``
(trade-ngin/src/instruments/contract_multiplier.cpp) so that the engine and the
dashboard cannot price the same position differently.

WHAT THIS DELIBERATELY DOES NOT DO
----------------------------------
trade-ngin's ``InstrumentRegistry::get_instrument`` rewrites ``ES`` to ``MES``,
``YM`` to ``MYM`` and ``NQ`` to ``MNQ`` before every lookup -- that deployment
reads a full-size equity-index ticker as the micro contract. AlgoLens does not,
and never has. If production metadata carries both rows, the engine and this
application will differ by a factor of ten on equity-index exposure.

That is not fixed here, because fixing it in either direction is a ten-times
change to a published exposure figure, and which direction is right depends on
the contract the fund actually holds. It is recorded in QT_PLATFORM_AUDIT.md
with the query that settles it.
"""

from algolens.domain.portfolio.instruments import base_symbol

#: Price quoted in the underlying's own unit: dollars per barrel, per ounce, per
#: index point. Contract size and price multiplier coincide.
PER_UNIT = 1.0

#: Price quoted in cents per unit -- bushels, pounds. One point is a cent.
CENTS = 0.01

#: Price quoted as a percentage of face value. One point is one per cent of it.
PERCENT_OF_PAR = 0.01

#: Root symbol -> (contract size in underlying units, quote-convention scale).
#: Their product is the price multiplier. Kept in step with the table in
#: trade-ngin/src/instruments/contract_multiplier.cpp.
CONTRACT_SPECS = {
    # Equity index, quoted in index points.
    "ES": (50.0, PER_UNIT),
    "MES": (5.0, PER_UNIT),
    "NQ": (20.0, PER_UNIT),
    "MNQ": (2.0, PER_UNIT),
    "YM": (5.0, PER_UNIT),
    "MYM": (0.5, PER_UNIT),
    "RTY": (50.0, PER_UNIT),
    "M2K": (5.0, PER_UNIT),
    # Interest rates, quoted as a percentage of par. Contract size is face value.
    "ZT": (200000.0, PERCENT_OF_PAR),
    "ZF": (100000.0, PERCENT_OF_PAR),
    "ZN": (100000.0, PERCENT_OF_PAR),
    "TN": (100000.0, PERCENT_OF_PAR),
    "ZB": (100000.0, PERCENT_OF_PAR),
    "UB": (100000.0, PERCENT_OF_PAR),
    # FX, quoted in USD per unit of the foreign currency.
    "6A": (100000.0, PER_UNIT),
    "6B": (62500.0, PER_UNIT),
    "6C": (100000.0, PER_UNIT),
    "6E": (125000.0, PER_UNIT),
    "6J": (12500000.0, PER_UNIT),
    "6M": (500000.0, PER_UNIT),
    "6N": (100000.0, PER_UNIT),
    "6S": (125000.0, PER_UNIT),
    "M6A": (10000.0, PER_UNIT),
    "M6B": (6250.0, PER_UNIT),
    "M6E": (12500.0, PER_UNIT),
    "MSF": (12500.0, PER_UNIT),
    # Metals, quoted per ounce or per pound.
    "GC": (100.0, PER_UNIT),
    "MGC": (10.0, PER_UNIT),
    "SI": (5000.0, PER_UNIT),
    "SIL": (1000.0, PER_UNIT),
    "HG": (25000.0, PER_UNIT),
    "PL": (50.0, PER_UNIT),
    "PA": (100.0, PER_UNIT),
    # Energy, quoted per barrel, MMBtu or gallon.
    "CL": (1000.0, PER_UNIT),
    "MCL": (100.0, PER_UNIT),
    "BZ": (1000.0, PER_UNIT),
    "NG": (10000.0, PER_UNIT),
    "RB": (42000.0, PER_UNIT),
    "HO": (42000.0, PER_UNIT),
    # Grains and oilseeds, mostly quoted in cents.
    "ZC": (5000.0, CENTS),
    "ZS": (5000.0, CENTS),
    "ZW": (5000.0, CENTS),
    "KE": (5000.0, CENTS),
    "ZO": (5000.0, CENTS),
    "ZL": (60000.0, CENTS),
    # The two that are not: soybean meal is dollars per short ton and rough rice
    # dollars per hundredweight, so for these the contract size IS the
    # multiplier. A blanket "grains are quoted in cents" rule would be as wrong
    # in the other direction.
    "ZM": (100.0, PER_UNIT),
    "ZR": (2000.0, PER_UNIT),
    # Livestock, quoted in cents per pound.
    "LE": (40000.0, CENTS),
    "HE": (40000.0, CENTS),
    "GF": (50000.0, CENTS),
    # Volatility.
    "VX": (1000.0, PER_UNIT),
}

#: How a multiplier was arrived at. Logged, because a change of convention in
#: the metadata table is otherwise silent and worth a hundred times the money.
SCALED_CONTRACT_SIZE = "scaled_contract_size"
ALREADY_POINT_VALUE = "already_point_value"
REPORTED_UNRECOGNISED = "reported_unrecognised"
UNKNOWN_SYMBOL = "unknown_symbol"


def _matches(a, b):
    """Two figures agree at a relative tolerance.

    Relative, because these span 0.5 (micro Dow) to 12,500,000 (yen), and an
    absolute epsilon that suits one end is meaningless at the other.
    """
    scale = max(abs(a), abs(b), 1.0)
    return abs(a - b) <= 1e-9 * scale


def known_multiplier(symbol):
    """The price multiplier this contract's specification implies, or None."""
    spec = CONTRACT_SPECS.get(base_symbol(symbol))
    if spec is None:
        return None
    contract_size, quote_scale = spec
    return contract_size * quote_scale


def resolve_multiplier(symbol, reported):
    """``(multiplier, how)`` for a figure read from ``"Contract Size"``.

    Recognises the reported figure as either a contract size or an
    already-scaled point value, and says which. Where the two coincide -- most
    contracts -- both readings give the same answer and the question does not
    arise.

    An unrecognised figure is passed through rather than discarded: the position
    still has to be priced, and the caller logs that nobody checked it.
    """
    spec = CONTRACT_SPECS.get(base_symbol(symbol))
    if spec is None:
        return reported, UNKNOWN_SYMBOL

    contract_size, quote_scale = spec
    multiplier = contract_size * quote_scale

    if _matches(reported, contract_size):
        return multiplier, SCALED_CONTRACT_SIZE
    if _matches(reported, multiplier):
        return reported, ALREADY_POINT_VALUE
    return reported, REPORTED_UNRECOGNISED
