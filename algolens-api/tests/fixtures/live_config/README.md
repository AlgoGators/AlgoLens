# Native baseline fixtures

These JSON files were exported by the actual `live_config_validate --export-base`
from Trade issue-88-config-contract's reviewed schema-2 templates, using the local
Debug `/tmp/issue88-build` artifact (generated engine identity `e89fa5d`, including
Task 2 working sources later committed at `8e62fea`). They are test baselines, not
release artifacts or deployment pins. No Python canonical hash is authoritative.

`conservative.json` and `equity_mr.json` use their matching template portfolios.
`equity_composite.json` uses the equity template with the raw `MEAN_REVERSION`
definition copied to `ALPHA` and `BETA` at 0.5 allocation each, then exported
through the native tool. Defaults exclude private database configuration and
legacy schema-1 risk defaults. All native annotations remain unchanged.
