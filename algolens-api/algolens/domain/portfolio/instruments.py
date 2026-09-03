"""Symbols and contract sizes, defined the way the engine defines them.

A futures position is not worth ``quantity x price``. It is worth
``quantity x price x contract size``, and the contract size is a property of the
instrument, not of the trade. AlgoLens computed notional without it, so every
exposure figure on screen was understated by the size of the contract: twelve ES
at 5,280.25 read as $63,363 rather than $3,168,150.

That is not a rounding error, and it is not only cosmetic. The same figure is
what the risk gate compares against published limits, so a gate fed notional
that is 50x too small will not fire when it should.

The two rules here mirror trade-ngin exactly, and cite where:

* ``base_symbol`` -- ``BacktestPnLManager::extract_base_symbol``. Market data
  carries continuous-contract suffixes (``ES.v.0``); contract metadata is keyed
  on the plain root (``ES``).
* ``notional`` -- ``chart_generator.cpp``: ``abs(quantity * price * multiplier)``.
"""


def base_symbol(symbol):
    """``ES.v.0`` -> ``ES``. The root a contract's metadata is filed under.

    Mirrors the engine's extract_base_symbol: strip at the first ``.v.`` or
    ``.c.`` marker and keep what precedes it.
    """
    if symbol is None:
        return None
    text = str(symbol)
    for marker in (".v.", ".c."):
        index = text.find(marker)
        if index != -1:
            text = text[:index]
    return text


def notional(quantity, price, multiplier):
    """Exposure in currency, or None when it cannot honestly be computed.

    None rather than zero, and None rather than a quantity-times-price figure
    that omits the contract size. A number that is wrong by a factor of the
    contract size is worse than an admitted gap: the gap is visible, and the
    wrong number is not.
    """
    if quantity is None or price is None or multiplier is None:
        return None
    return abs(float(quantity) * float(price) * float(multiplier))
