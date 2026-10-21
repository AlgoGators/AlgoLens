"""A realistic daily-report payload (schema_version 1), for tests and the preview script."""

import random
from datetime import date, timedelta


def sample_payload(with_notice=True, days=30, seed=7):
    rng = random.Random(seed)
    end = date(2026, 10, 21)
    dates = [(end - timedelta(days=days - 1 - i)).isoformat() for i in range(days)]
    equity, value = [], 1_000_000.0
    pnl = []
    for d in dates:
        change = rng.gauss(2500, 9000)
        value += change
        pnl.append({"date": d, "value": round(change, 2)})
        equity.append({"date": d, "value": round(value, 2)})

    positions = [
        ("ES", "E-mini S&P 500", 2, 5412.25, 541225),
        ("NQ", "E-mini Nasdaq-100", -1, 19120.50, -956025),
        ("ZN", "10-Year T-Note", 3, 111.28, 334_000),
        ("CL", "Crude Oil", -2, 68.42, -136_840),
        ("GC", "Gold", 1, 2341.90, 234_190),
        ("6E", "Euro FX", 4, 1.0832, 541_600),
    ]
    total = sum(abs(p[4]) for p in positions)
    payload = {
        "schema_version": 1,
        "report_date": end.isoformat(),
        "portfolio_id": "LIVE_TREND_FOLLOWING",
        "portfolio_name": "Trend Following",
        "notices": [],
        "positions": [
            {"symbol": s, "name": n, "quantity": q, "price": p, "notional": notional,
             "weight": abs(notional) / total}
            for s, n, q, p, notional in positions
        ],
        "executions": [
            {"symbol": "ES", "side": "buy", "quantity": 1, "price": 5412.25,
             "notional": 270612.5, "cost": 2.10},
            {"symbol": "CL", "side": "sell", "quantity": 2, "price": 68.42,
             "notional": 136840, "cost": 4.20},
            {"symbol": "ZN", "side": "buy", "quantity": 1, "price": 111.28,
             "notional": 111280, "cost": 2.10},
        ],
        "realized": {
            "label": "2026-10-20",
            "positions": [
                {"symbol": "ES", "quantity": 1, "entry_price": 5380.0, "exit_price": 5412.25, "pnl": 1612.5},
                {"symbol": "CL", "quantity": -2, "entry_price": 69.1, "exit_price": 68.42, "pnl": 1360.0},
                {"symbol": "NQ", "quantity": -1, "entry_price": 19050.0, "exit_price": 19120.5, "pnl": -1410.0},
                {"symbol": "GC", "quantity": 1, "entry_price": 2330.0, "exit_price": 2341.9, "pnl": 1190.0},
            ],
        },
        "metrics": [
            {"label": "Portfolio VaR", "value": "1.84%"},
            {"label": "Total margin posted", "value": "$412,300"},
            {"label": "Volatility", "value": "9.6%"},
            {"label": "Cost per $1M traded", "value": "$7.80"},
        ],
        "series": {
            "equity": equity,
            "daily_pnl": pnl,
            "pnl_by_symbol": [
                {"symbol": "ES", "value": 1612.5}, {"symbol": "CL", "value": 1360.0},
                {"symbol": "NQ", "value": -1410.0}, {"symbol": "GC", "value": 1190.0},
                {"symbol": "ZN", "value": -320.0}, {"symbol": "6E", "value": 640.0},
            ],
            "composition": [
                {"label": "Equity index", "value": 34}, {"label": "Rates", "value": 22},
                {"label": "Energy", "value": 15}, {"label": "Metals", "value": 12},
                {"label": "FX", "value": 10}, {"label": "Ags", "value": 7},
            ],
        },
        "rollovers": [{"symbol": "CL", "current": "CLZ6", "next": "CLF7"}],
        "footnotes": [
            "This strategy is based on daily OHLCV data. Only the front-month contract is covered.",
            "All values reflect a trading start date of October 5th, 2025.",
        ],
    }
    if with_notice:
        payload["notices"].append({
            "kind": "holiday",
            "title": "Yesterday was Columbus Day",
            "body": ("The latest futures settlement prices are not available, as futures markets "
                     "were closed yesterday (2026-10-12). PnL for these contracts will be updated "
                     "in the next report once settlement data is released."),
            "footnote": "Please continue to monitor your positions closely.",
        })
    return payload
