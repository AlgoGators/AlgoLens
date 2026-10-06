# Synthetic container isolation gate

Run `python3 deployment/qt_container_smoke/run.py --sha <full-HEAD-SHA>` on a
Linux x86_64 host with local Docker and Compose. The driver archives the exact
commit and builds the production backend Dockerfile from those bytes. It checks
the image revision label and the executed container's immutable image ID.

The fixture image compiles a tiny synthetic ELF evaluator and engine, bundles
their real dynamic loader, crypto and transitive libraries, and computes the
same closed bundle manifest used by the application. The production application
image runs the real `QtEvaluatorProcess` / `QtEvaluatorBundle` code against a
read-only bind mount. The native fixture verifies sealed memfd execution,
absence of inherited application credentials, and only loopback network
interfaces inside the evaluator's newly created user/network namespace.

The smoke container has no network, published ports, production files, or
credentials. All names and data are synthetic. No SSH, registry upload,
deployment, service restart, or production database access occurs. Images remain
local; named containers and temporary archives/bundles are removed on exit.

No privileged mode or seccomp/AppArmor bypass is supplied. If the host's Docker
policy blocks `unshare -Urn`, this gate fails; review and prove the intended
runtime isolation configuration before deployment. A passing smoke proves
packaging, mounts and transport isolation, not financial evaluator semantics,
database migrations, live worker liveness, or production readiness. Those remain
separate acceptance gates against the real pinned trade-ngin release bundle.

## Runtime readiness integration

`scripts/production_readiness.py --rehearsal-root <private-root>` explicitly
selects `qt_rehearsal_migrated` at that root's Unix socket with role
`qt_algolens_api`; production remains fixed to `new_algo_data`. Rehearsal
application composition retains production JWT/CORS/capability controls.

The schema/role catalog wire format matches the integrated rehearsal harness,
including role membership, column/default ACLs, function search paths and RLS.
Columns are read from PostgreSQL catalogs so a limited API sees the same schema
fingerprint as the migration administrator. Runtime identity verifies database,
current role and server address; it does not independently read the privileged
`data_directory` setting. The mutation/rehearsal harness still verifies that
setting, and the reviewed database identity manifest remains hash-bound.

Worker readiness requires a visible `qt_worker` session with application name
`qt_desk_worker`, no unfinished job older than five minutes, and no expired
running lease. This needs API column SELECT on `state`, `first_seen_at`, and
`lease_expires_at` in `trading.qt_desk_dispatch_jobs`. It does not grant broad
statistics access. A visible session is a liveness signal, not independent proof
of the worker's executable bytes; installed worker identity remains a release
and worker-host attestation requirement.
