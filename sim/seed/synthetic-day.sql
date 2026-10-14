-- One QT day for the synthetic fixture: enough for the desk panel to render and for the
-- clock rules (09:30 send, 10:00 cutoff) to be exercised. Not market data: no engine run can
-- succeed on it (that needs the prod snapshot).
--
--   2026-10-14  previous day: three books, published by the 10:00 fallback and sent
--   2026-10-15  the sim day: the model run's three books (qt_proposal and qt = system),
--               not published
--
-- Symbols: ZT, ZN, GC, CL, 6E (continuous .v.0), bars for 2026-10-12..14.

BEGIN;

INSERT INTO metadata.contract_metadata
    ("Databento Symbol", "IB Symbol", "Name", "Exchange", "Asset Type", "Sector", "Contract Size")
VALUES
    ('ZT', 'ZT', '2-Year T-Note', 'CBOT', 'Futures', 'Rates', '200000'),
    ('ZN', 'ZN', '10-Year T-Note', 'CBOT', 'Futures', 'Rates', '100000'),
    ('GC', 'GC', 'Gold', 'COMEX', 'Futures', 'Metals', '100'),
    ('CL', 'CL', 'Crude Oil', 'NYMEX', 'Futures', 'Energy', '1000'),
    ('6E', 'EUR', 'Euro FX', 'CME', 'Futures', 'FX', '125000');

INSERT INTO futures_data.ohlcv_1d (time, symbol, open, high, low, close, volume)
SELECT d::timestamptz, s.symbol, s.px, s.px * 1.002, s.px * 0.998, s.px * (1 + 0.001 * i), 10000
FROM (VALUES ('ZT.v.0', 103.5), ('ZN.v.0', 111.2), ('GC.v.0', 2650.0),
             ('CL.v.0', 71.4), ('6E.v.0', 1.09)) AS s(symbol, px)
CROSS JOIN LATERAL (
    SELECT g::date AS d, row_number() OVER () AS i
    FROM generate_series('2026-10-12'::date, '2026-10-14'::date, '1 day') g
) days;

-- Three books a day for the desk portfolio, the system book for its model twin.
INSERT INTO trading.positions
    (symbol, quantity, average_price, daily_unrealized_pnl, daily_realized_pnl, last_update,
     strategy_id, strategy_name, date, portfolio_id, portfolio_type)
SELECT p.symbol, p.qty, p.px, 0, 0, (b.day + time '07:00') AT TIME ZONE 'America/New_York',
       'TREND_FOLLOWING', 'TREND_FOLLOWING', b.day, b.portfolio_id, b.book
FROM (VALUES ('ZT.v.0', 8, 103.6), ('ZN.v.0', -3, 111.3), ('GC.v.0', 2, 2652.0),
             ('CL.v.0', 0, 71.5), ('6E.v.0', -4, 1.091)) AS p(symbol, qty, px)
CROSS JOIN (VALUES
    (date '2026-10-14', 'QT_CONSERVATIVE_PORTFOLIO', 'system'),
    (date '2026-10-14', 'QT_CONSERVATIVE_PORTFOLIO', 'qt_proposal'),
    (date '2026-10-14', 'QT_CONSERVATIVE_PORTFOLIO', 'qt'),
    (date '2026-10-15', 'QT_CONSERVATIVE_PORTFOLIO', 'system'),
    (date '2026-10-15', 'QT_CONSERVATIVE_PORTFOLIO', 'qt_proposal'),
    (date '2026-10-15', 'QT_CONSERVATIVE_PORTFOLIO', 'qt'),
    (date '2026-10-14', 'QT_CONSERVATIVE_MODEL_PORTFOLIO', 'system'),
    (date '2026-10-15', 'QT_CONSERVATIVE_MODEL_PORTFOLIO', 'system')
) AS b(day, portfolio_id, book);

INSERT INTO trading.equity_curve (strategy_id, timestamp, equity, portfolio_id, portfolio_type)
SELECT 'TREND_FOLLOWING', (d + time '16:00') AT TIME ZONE 'America/New_York',
       500000 + 1500 * row_number() OVER (PARTITION BY pid, book ORDER BY d), pid, book
FROM generate_series('2026-10-12'::date, '2026-10-14'::date, '1 day') d
CROSS JOIN (VALUES ('QT_CONSERVATIVE_PORTFOLIO', 'system'), ('QT_CONSERVATIVE_PORTFOLIO', 'qt'),
                   ('QT_CONSERVATIVE_MODEL_PORTFOLIO', 'system')) AS x(pid, book);

INSERT INTO trading.live_results
    (strategy_id, portfolio_id, date, current_portfolio_value, daily_return, gross_leverage,
     net_leverage, portfolio_type, created_at)
SELECT 'TREND_FOLLOWING', pid, d, 504500, 0.003, 1.2, 0.4, book,
       (d + time '07:00') AT TIME ZONE 'America/New_York'
FROM (VALUES (date '2026-10-14'), (date '2026-10-15')) AS days(d)
CROSS JOIN (VALUES ('QT_CONSERVATIVE_PORTFOLIO', 'system'), ('QT_CONSERVATIVE_PORTFOLIO', 'qt'),
                   ('QT_CONSERVATIVE_MODEL_PORTFOLIO', 'system')) AS x(pid, book);

-- 2026-10-14 published by the 10:00 fallback and sent; 2026-10-15 built at 07:00, unpublished.
INSERT INTO trading.live_run_metadata
    (date, strategy_id, portfolio_id, created_at, published_by, published_at, publish_source,
     sent_at)
VALUES
    ('2026-10-14', 'TREND_FOLLOWING', 'QT_CONSERVATIVE_PORTFOLIO',
     '2026-10-14 07:00 America/New_York', 'system:fallback-10am',
     '2026-10-14 10:00 America/New_York', 'fallback', '2026-10-14 10:00 America/New_York'),
    ('2026-10-15', 'TREND_FOLLOWING', 'QT_CONSERVATIVE_PORTFOLIO',
     '2026-10-15 07:00 America/New_York', NULL, NULL, NULL, NULL),
    ('2026-10-14', 'TREND_FOLLOWING', 'QT_CONSERVATIVE_MODEL_PORTFOLIO',
     '2026-10-14 07:00 America/New_York', 'system:model-only',
     '2026-10-14 07:00 America/New_York', 'model-only', '2026-10-14 09:30 America/New_York'),
    ('2026-10-15', 'TREND_FOLLOWING', 'QT_CONSERVATIVE_MODEL_PORTFOLIO',
     '2026-10-15 07:00 America/New_York', 'system:model-only',
     '2026-10-15 07:00 America/New_York', 'model-only', NULL);

COMMIT;
