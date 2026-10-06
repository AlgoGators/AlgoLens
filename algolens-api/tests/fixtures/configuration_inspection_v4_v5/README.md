# Native configuration publication handoff fixtures

All inputs are synthetic and local. Documents were captured from native PostgreSQL publication, never rebuilt or assigned hashes by Python/TypeScript. `.evidence.json` contains the actual frozen selection, classified terminal safety, and applicable runtime intent/attempt rows. `.http.json` contains the actual Flask response after JSONB insertion and SQL-reader verification. These are Debug acceptance fixtures, not production release attestations.

| Publication | Native build | Source day | Scope | SHA256 of captured JSON file |
|---|---|---|---|---|
| futures-v4 | `bb34bc9` | 2026-09-22 | registered HOUSE | `6675782e0f24d5e0ca7998afdc7951a02dae1a0be364ca78c21a298174690ce5` |
| equity_house-v5 | `bb34bc9` | 2026-08-12 | registered HOUSE | `26dc04f140cee88cbe4ff9d220abb050748bbb9655feaa23a352c223a5f79e66` |
| equity_multi-v5 | `bb34bc9` | 2026-08-12 | registry-less investor; domain only | `7cd0ba07b7fc5b1d70decbd91145cf44c1d02f14888d8afc7272a0814fe22c0b` |
| equity_now-v5 | `3f921d1` | 2026-10-06 | registered HOUSE | `af80af9af78fe6c57a4a688ad785be4b784695676a07fc131945e5c02cfbe1b1` |
| equity_empty_now-v5 | `3f921d1` | 2026-10-06 | registered HOUSE | `757e3e188d5b59bfe9e936b6fcca5fa31d1d5d0a7c0e5685b2760fd85d34b52f` |

Futures: actual controlled approved-override runner probe with native validation and runtime approval. HOUSE composite: `EquityMultiLivePg` synthetic integration runner and completed 2026-08-12 source day. Investor composite: same native integration runner, raw source allocations 2+2, native owner identities ALPHA/BETA, no registry/controlled authority. MR and empty MR: actual `live_equity_mr` run with no-delivery preload guard, raw source allocation 2, native owner `EQUITY_MEAN_REVERSION`.

The older Task4 investor capture used 2026-11-04 source day with an October capture timestamp: valid only as a native-scope synthetic test input, unsuitable for completed HTTP report acceptance. The runner dates were shifted by 84 days (weekday-preserving) and a new actual native capture generated. No output JSON date rewriting or future-date exemption was used.

Investor evidence is accepted directly by the domain parser; registry-based HTTP intentionally remains unavailable. The actual HOUSE capture supplies the composite HTTP acceptance. Existing historical v1/v2/v3 fixtures elsewhere remain unchanged.
