# AlgoLens deployment preparation

Production remains read-only. **Do not send any emails.** No checklist or workflow
input replaces the user's explicit authorization.

## Current release procedure

The only current procedure is the [guarded exact-SHA rollout](deployment/ROLLOUT.md).
It requires a tested commit, coordinated schema verification, backup/rollback
evidence, maintenance approval, protected-environment controls and a verified
existing Compose frontend/backend pair. It never automatically applies a migration.

The prepared workflow is manual-only; pushing to main does not deploy. It updates
the serving API on loopback5000 and frontend on loopback3000, then checks source
identity through Nginx and loopback. Nginx is the public proxy, not the application
backend. The port5001 systemd backend is legacy and is not updated by this workflow.

The historical npx frontend must first undergo a separately approved host cutover.
Until both serving containers are verified, the helper refuses before build/update.
Neither that cutover nor any production verification has been performed here.

## Schema and environment contracts

The read-only checker is [check_schema.py](algolens-api/scripts/check_schema.py);
the declared contract is [schema_contract.py](algolens-api/algolens/infrastructure/db/schema_contract.py).
The broader [readiness script](algolens-api/scripts/production_readiness.sh) is a
separate approved diagnostic, not a migration or permission to access production.
Migration012 must be coordinated with compatible application code under its
dedicated rollout plan; no numeric ordering shortcut replaces that review.

Keep runtime secrets outside Git and outside frontend build context. The prepared
Compose file requires an explicitly verified absolute runtime env-file path and
an exact release SHA. The frontend receives only its public API origin/release ID.

## Historical reference only

[Archived installation notes](deployment/HISTORICAL_DEPLOYMENT_2026-09-21.md)
preserve previous operational context. Their mutable-main, service-restart and
migration examples are obsolete, **not current instructions**, and must not be
used to bypass the guarded rollout. For endpoint routing, the existing /auth and
/portfolio prefixes already proxy to5000; other roots require a separately reviewed
Nginx route (the prepared /version route is one example).
