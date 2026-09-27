# Next-run control — prepared, not enabled

This local capability does not start or stop a process immediately. Metadata edits
are not execution approval. A controlled scheduled run must match an approved,
unchanged complete static strategy configuration. No subset allocation, capital
transfer, liquidation or email delivery is authorized by these controls.

## Defaults

- API and engine independently default `QT_RUNTIME_CONTROL_ENABLED` to disabled;
  only exact `true` enables that process's controlled path.
- `QT_RUNTIME_APPROVER_IDS` defaults empty. Approval requires both current stored
  admin role and an explicitly listed numeric user ID. No migration grants roles.
- Compose mounts the included empty manifest read-only at
  `/app/runtime-control/manifest.json`. Missing bind sources are not auto-created.
- `QT_EMAIL_DELIVERY_ENABLED` must remain absent or false. Runtime approval does
  not enable it. The current task prohibits all email delivery.

An unchanged migration-baseline live scope may retain its static legacy execution
when runtime control is disabled. Any lifecycle/identity/membership revision
blocks that legacy publication until separately approved controlled execution;
otherwise a metadata user could reactivate a retired scope without approval.
QT position edits themselves do not revise strategy configuration.

## Required reviewed manifest

The deployment owner may, only during a separately authorized rollout, provision
a credential-free JSON manifest and set `ALGOLENS_RUNTIME_MANIFEST_FILE` to its
verified absolute host path before rendering/releasing Compose. It is mounted
read-only; the API user must be able to read it. The manifest is not created from
browser input and should not contain database or email configuration.

Shape:

```json
{"version":1,"scopes":[{
  "registry_id":"reviewed-public-id",
  "portfolio_id":"REVIEWED_BOOK",
  "engine_strategy_id":"LIVE_EXACT_COMBINED_STRATEGY",
  "config_snapshot":"REPLACE WITH REVIEWED VERSIONED TRADING SNAPSHOT OBJECT"
}]}
```

The illustrative string above is intentionally not a valid executable snapshot.
Obtain the actual version1 trading snapshot from the compatible engine's typed
serializer and compare every financial/execution/strategy field with the exact
deployed static configuration. Do not copy `AppConfig::to_json()` wholesale: its
legacy representation includes credentials. The engine rechecks JSONB equality
at startup and publication; changing the manifest requires new review/requests.

The compatible TradeNgin migration013 adds revision/intent/attempt storage and
writer fences. It is distinct from012 and must pass prerequisite checks. Both
compatible application releases, controlled-writer rollout, recoverable backup,
maintenance window and schema verification are still required. No migration or
deployment is executed by this document or by reading status in the UI.

## Evidence, not assumptions

The UI separately shows pending requests, approval and actual engine attempts.
An API enabled setting does not prove the engine/scheduler enabled setting.
Applied/published means the producer committed its complete current-day payload
and acknowledgement together. Applied/stopped means it acknowledged an already
retired scope without publishing positions. Running without completion is not
success; failed attempts remain visibly failed. Earlier-day finalization uses
separately fenced transactions, not a claimed atomic rewrite of all history.

Only verify real scheduled adoption after separately approved rollout. Do not
start/restart cron, trigger a workflow, fabricate investor edits or send mail to
test these controls under the current production-read-only/no-email restriction.
