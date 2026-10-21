# AlgoLens migrations

Apply in the order below, after the trade-ngin migrations they depend on (trade-ngin
`migrations/README.md`). There is no migrations table (master document ruling 26): applied state
is tracked by hand in this file. When you apply a migration to a database, fill in the date in
its column in the same PR or straight after. A blank cell means "not recorded", not "not applied".

| # | File | What it does | Rollback | new_algo_data |
|---|---|---|---|---|
| 001 | `001_create_strategy_registry.sql` | `trading.strategy_registry`: the portfolios AlgoLens shows, by API id, with display metadata and starting equity; seeds the trend book | none (drop the table) | |
| 002 | `002_strategy_lifecycle.sql` | Lifecycle (`live`, `incubating`, `retired`) on the registry and `trading.strategy_lifecycle_log` | none | |
| 003 | `003_screen_access.sql` | `auth.user_screen_access` and `auth.screen_access_log` (member, investor and qt screens, admin-assigned) and `investor.reports` | `003_screen_access_rollback.sql` (destructive: back up first) | |
| 004 | `004_desk_settings_locks.sql` | `trading.desk_settings_locks` (the settings the QT desk sees greyed out, D-14; seeded with Dom's 2026-10-14 list) and its append-only log | `004_desk_settings_locks_rollback.sql` (drops the log) | |
| 005 | `005_investor_portfolio_links.sql` | `investor.portfolio_links`: the portfolio and book (QT or model) each investor follows (D-25, decision 13), with an append-only log | `005_investor_portfolio_links_rollback.sql` (every investor back to the QT book) | |
| 006 | `006_report_queue.sql` | `reports.report_queue`: reports trade-ngin enqueues and AlgoLens renders and emails (daily trading report) | `006_report_queue_rollback.sql` (destructive: unsent reports are lost) | |

The QT tables AlgoLens reads and writes (`trading.position_overrides`, `trading.strategy_config`,
the `portfolio_group` and `desk_editable` registry columns) are trade-ngin's migrations 021 to 029.
