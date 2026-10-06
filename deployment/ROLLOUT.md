# Prepared release — not permission to deploy

Production remains read-only and **all email sending is prohibited**. Nothing
in this document, workflow, checkbox or test supersedes those user restrictions.
The code here is a local repair proposal; no production command was run.

## Authoritative release unit

The prepared target is the existing production Compose definition: frontend on
127.0.0.1:3000 and backend on 127.0.0.1:5000, behind host Nginx. Nginx is still
the public reverse proxy; Flask/Gunicorn is the API backend. The legacy
`algolens-backend` systemd service on 5001 is not this serving target.

**This is a cutover prerequisite, not an observed production fact.** The
historical installation serves the frontend with `algolens.service` (npx).
The helper refuses while that service is active; it never stops it, guesses a
Compose project, creates a database, or applies migration012. An operator must
separately approve and execute the frontend host cutover. Both serving containers
must already exist under the verified Compose project with the exact loopback
port bindings before this update helper runs. It has no implicit first-install
mode; an absent, foreign, ambiguous or misbound frontend stops before build/up.
Until the operator-approved cutover is complete, the release cannot proceed.
Preserve old service/assets for rollback; do not remove them.

## Required before any future dispatch

1. New explicit authorization replacing the production read-only boundary,
   approved maintenance window, recoverable backup/restore evidence, named
   operator and rollback owner. The no-email prohibition remains in force.
2. Complete the coordinated, hash-pinned migration/application rollout plan
   separately. Production readiness must independently match the final database
   identity/schema manifest; a workflow boolean remains an authorization
   attestation, not a substitute for that machine check.
3. Verify actual Nginx routes, Compose project/container labels, loopback ports,
   runtime env file and frontend cutover. Install/test the reviewed `/version`
   Nginx route separately. The helper does not edit Nginx or disable services.
4. Configure a protected GitHub `production` environment with required reviewers
   and deployment branch rules. Local tests do NOT verify those controls.
5. Set `ALGOLENS_COMPOSE_PROJECT`, `ALGOLENS_RUNTIME_ENV_FILE` (absolute server
   path; do not expose its values), and `ALGOLENS_PUBLIC_ORIGIN`. Also provision
   absolute operator-controlled paths for `ALGOLENS_EVALUATOR_BUNDLE_DIR`,
   `ALGOLENS_RELEASE_ARTIFACT_MANIFEST`, `ALGOLENS_DATABASE_IDENTITY_MANIFEST`,
   `ALGOLENS_RUNTIME_MANIFEST_FILE`, and `ALGOLENS_RELEASE_EVIDENCE_DIR`. The
   release helper computes the runtime manifest's exact SHA-256 and passes it as
   `QT_RUNTIME_CONFIG_SHA256`; the backend rejects any different mounted bytes.
   Never copy
   database secrets into frontend env. Configure `EC2_HOST`, `EC2_USER` and
   `EC2_SSH_KEY` secrets and `ALGOLENS_SSH_KNOWN_HOSTS` from an independently
   verified server host public key. The prepared SSH step rejects unknown or
   changed keys; do not populate trust with an unverified network scan.
6. Retain current image IDs/digests, frontend artifacts, Compose settings,
   previous source SHA and Nginx config. Confirm rollback compatibility with
   the approved migration manifest; never automatically reverse audit data.

## Staged dependency boundary

This branch contains checked-in `dependency-placeholder` fixtures only. They
version and test consumer interfaces but can never return ready. Candidate
acceptance requires all four final inputs:

1. T1 `qt-capabilities/v1`: resolved digest and a runtime probe proving the
   internal capability boundary is installed.
2. T2 `release-artifacts/v1`: the concrete T2 schema from commit `d3468cd`,
   including exact source/build/image/evaluator identity, all eight artifacts,
   a canonical manifest self-hash, and `integration.pending_artifacts=[]`.
   T5 owns the deterministic no-side-effect evaluator request and validates and
   hashes the actual response; that handshake is not an invented T2 field.
3. T3 `algolens-database-identity/v1`: exact `new_algo_data` server address,
   data directory, limited API role, schema digest/probe implementation, and
   the sole supported lifecycle-live book with matching evaluator pins.
4. T4 `qt-worker-service/v1`: resolved digest and a runtime probe proving the
   separate worker service is installed and healthy.

`evaluate_runtime_readiness` supplies the concrete schema, role, capability and
worker probes to both `/ready` and the CLI. Schema/role callbacks query the
active read-only transaction and return 64-hex catalog digests. Runtime roles
with superuser, create-role, create-database, replication, or bypass-RLS flags
are refused. Capability readiness resolves exactly one non-retired user per
approved normalized email before checking roles and exact user-ID-bound grants
and approver mappings. Worker readiness checks the pinned contract, visible
worker session and governed queue age/lease state. An unresolved manifest,
unexpected live book or identity mismatch returns HTTP 503. `/health` remains
process-only liveness. Deep readiness probes are serialized and cached for at
most five seconds; responses always use `Cache-Control: no-store`.

The CLI's explicit `--rehearsal-root` and matching app factory argument bind
all authenticated requests, repository connections and readiness checks to
one private socket-only `qt_rehearsal_migrated` connector. No database password
is required for the private trust-authenticated cluster. Any inherited `PG*`
libpq configuration with a nonempty value is refused; no environment service,
host address or options can redirect the connection. A rehearsal connection
without its bound application context is refused. Production still uses its
existing explicitly configured connector and requires `new_algo_data`.

`app_factory.py` installs T1's `install_capability_guard`
only after all blueprints plus `/version`, `/health`, and `/ready` are present;
those three endpoints are the only explicit application-level open routes.

### Environment-specific database attestations are a hard gate

The catalog digest includes all non-system schemas and the role digest includes
all `qt_*` roles, object owners, ACLs, RLS and function security settings. A
rehearsal clone may omit non-admitted schemas, Timescale objects or indexes and
normalize owners; it also has a rehearsal administrator. Its final digest is
therefore not automatically the production final digest. The current release
helper compares readiness against the operator-supplied identity manifest; it
does not translate clone digests or generate production expectations.

Retain separate hash-pinned rehearsal and production identity manifests.
Rehearsal evidence binds the private database/root, exact migration ledger and
its resulting catalog. Before an authorized production rollout, establish and
review the expected production final catalog using a production-faithful
catalog/ownership rehearsal or an explicitly audited transformation from the
verified production baseline and exact migration ledger. Record every omitted
schema/object and ownership/role difference. Capture expected production
schema/role digests before accepting the production candidate; compare those
expectations to read-only post-migration runtime attestation. Never copy the
clone digest into a manifest renamed `new_algo_data`, ignore a mismatch, or
replace the expected value with an unreviewed observed production value.

Until this production expectation is independently established, production
acceptance remains blocked even if the private clone is green. Runtime does
not query privileged `data_directory`; the rehearsal/mutation harness retains
its exact data-directory guard. No settings/statistics privileges are added
to runtime accounts for this process.

The checked-in host Nginx configuration does not currently expose backend
`/ready`. Add and independently review an exact no-cache proxy route during the
coordinator-owned integration/cutover. Until loopback and public `/ready` both
return the fixed ready payload, the release helper fails without success
evidence.

## Prepared workflow behavior

Manual-only, serialized dispatch requires four operational attestations. It
checks the latest completed main push CI run for the requested exact40hex SHA,
fetches/checks out that SHA in a clean checkout, then verifies HEAD again.
It builds both images before recreating either, records their content-addressed
image IDs, and runs the backend candidate container's read-only production
preflight before replacing either serving container. It then updates
backend5000 and frontend3000, runs the same preflight inside the installed
backend, requires its canonical evidence to equal the candidate evidence,
waits for `/ready`, proves each running image ID equals the built ID, and
compares public and loopback API `/version`, frontend `/release.json`, and
readiness.

Readiness opens the database transaction read-only; checks exact database
name/server/data-directory/current-role identity; rejects privileged role
flags; compares the T3 role and schema digests; independently checks the exact
live registry and policy sets so an unsupported live book cannot disappear in
a join; requires the sole expected lifecycle-live book; compares its evaluator
pins with T2; verifies the mounted runtime-config bytes; and launches the
deterministic evaluator handshake through the sealed bundle. Public payloads
contain only a fixed set of check statuses.

No `git pull main`, host backend pip install, legacy5001 restart, automatic
migration or mail call. Builds still depend on base-image/dependency registries;
an exact source SHA is not bit-for-bit build reproducibility or digest promotion.

Build or candidate-preflight failure does not update containers. An update or
identity failure fails the workflow without a success claim or automatic
database rollback. Multi-container startup is not atomic. Success writes one
mode-restricted `algolens-release-evidence/v1` record named by the full SHA.
Its self-hash binds source SHA, built/running image IDs, trade-ngin/evaluator
identities, schema/database/role identity, manifest/runtime-config hashes,
dependency digests, supported books, the evaluator response hash, exact public
and loopback endpoint payload hashes, the candidate/installed readiness
evidence digests, and UTC time. The file is created without overwrite at mode
0600 and both file and directory metadata are synced. It excludes passwords, DSNs,
environment contents, and the data directory path.

## Offline evidence

`python deployment/test_release.py` fakes all external commands. It checks
approval gates, contract/path refusal, dirty/mismatched source, legacy frontend
refusal, candidate-preflight ordering, the serving-pair update, installed-image
mismatch, endpoints, and evidence hashing. It is **not** an SSH,
Docker-image, GitHub-policy, Nginx or production-deployment certification.

The CI-query action is pinned to a full reviewed
[github-script v7 revision](https://github.com/actions/github-script/commit/f28e40c7f34bde8b3046d885e986cb6290c5673b).
Deployment uses runner-native OpenSSH with strict, preverified host-key checking,
not a third-party action that downloads its SSH executable at runtime. Temporary
key files are permission-restricted and removed on step exit. Changes to the action
pin require review; this is not a transitive dependency/CVE or runner-image audit.
