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
2. Complete the coordinated migration012/application rollout plan separately.
   Verify schema with the existing read-only checker and review SQL evidence;
   a workflow boolean is an attestation, not an automated database audit.
3. Verify actual Nginx routes, Compose project/container labels, loopback ports,
   runtime env file and frontend cutover. Install/test the reviewed `/version`
   Nginx route separately. The helper does not edit Nginx or disable services.
4. Configure a protected GitHub `production` environment with required reviewers
   and deployment branch rules. Local tests do NOT verify those controls.
5. Set `ALGOLENS_COMPOSE_PROJECT`, `ALGOLENS_RUNTIME_ENV_FILE` (absolute server
   path; do not expose its values), and `ALGOLENS_PUBLIC_ORIGIN`. Never copy
   database secrets into frontend env. Configure `EC2_HOST`, `EC2_USER` and
   `EC2_SSH_KEY` secrets and `ALGOLENS_SSH_KNOWN_HOSTS` from an independently
   verified server host public key. The prepared SSH step rejects unknown or
   changed keys; do not populate trust with an unverified network scan.
6. Retain current image IDs/digests, frontend artifacts, Compose settings,
   previous source SHA and Nginx config. Confirm rollback compatibility with
   migration012; never automatically reverse an audit-data migration.

## Prepared workflow behavior

Manual-only, serialized dispatch requires four operational attestations. It
checks the latest completed main push CI run for the requested exact40hex SHA,
fetches/checks out that SHA in a clean checkout, then verifies HEAD again.
It builds both images before recreating either, updates backend5000 and
frontend3000, waits for container health, and compares public and loopback
API `/version` and frontend `/release.json` with the expected SHA.
Version checks do not query the database. The backend's separate healthcheck
performs its existing read-only database check.

No `git pull main`, host backend pip install, legacy5001 restart, automatic
migration or mail call. Builds still depend on base-image/dependency registries;
an exact source SHA is not bit-for-bit build reproducibility or digest promotion.

Build failure does not update containers. Update/identity failure fails the
workflow: no success claim or automatic database rollback. Use the approved
maintenance rollback plan. Multi-container startup is not an atomic transaction.

## Offline evidence

`python deployment/test_release.py` fakes all external commands. It checks
approval gates, dirty/mismatched source, legacy frontend refusal, the serving
Compose-pair update and installed-identity mismatch. It is **not** an SSH,
Docker-image, GitHub-policy, Nginx or production-deployment certification.

The CI-query action is pinned to a full reviewed
[github-script v7 revision](https://github.com/actions/github-script/commit/f28e40c7f34bde8b3046d885e986cb6290c5673b).
Deployment uses runner-native OpenSSH with strict, preverified host-key checking,
not a third-party action that downloads its SSH executable at runtime. Temporary
key files are permission-restricted and removed on step exit. Changes to the action
pin require review; this is not a transitive dependency/CVE or runner-image audit.
