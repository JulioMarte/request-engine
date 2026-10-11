# Operational implementation — 2026-10-10

This checkpoint extends PR #137 on `feature/admin-console`. The repository is
pre-production; no installation, external SMTP account, off-host recovery bundle,
operator receiver, or deployment firewall has been supplied. Implemented tooling
and laboratory proof must not be reported as productive acceptance.

| Area | Implemented path | Required installation evidence |
| --- | --- | --- |
| Productive load | Bounded count or sustained-duration HTTP probe; full-response latency, throughput, concurrency and request-cap evidence | Approved workload against the deployed immutable candidate, host/pool observations and capacity objectives |
| Shared limits | Migration 0038 and PostgreSQL authentication admission across replicas; bounded state, lock/query/transaction deadlines, fail-closed mismatch and unavailable state | Coordinated limit configuration, ingress abuse controls, deployed replica/load proof |
| Scheduled retention | Hardened systemd one-shot and persistent timer renderer; protected DSN credential and one bounded deletion batch per invocation | Installed timer, dedicated login, actual scheduling and backlog evidence |
| External mail | Unique send/message identifiers, durable ambiguous-submission evidence, separate exact-ID mailbox receipt verification | Real provider policy, TLS/credentials, mailbox receipt and throttling evidence |
| Real restore | Dumps preserve owners/ACL/RLS; legacy unsafe restores rejected; transactional restore; referenced restore evidence checked by drill certification | Off-host bundle, independent fenced environment, fresh destination credentials, reads/secrets/offline-recovery proofs and observed RPO/RTO |
| Complete alerts | Worker telemetry, migration 0039 aggregate-only monitor, protected recovery-certification freshness gauges, optional immutable image build, Collector/Prometheus/Alertmanager configuration, alert rule fixtures and local firing/resolved receipt smoke | Monitoring credentials and route, real receiver receipt/acknowledgement, independent Watchdog monitor, approved freshness thresholds and expected instance inventory |
| Deployment network | Immutable HTTP Compose renderer with private control binding and explicit proxy trust; exact-IP TCP/TLS acceptance probe | Public and private probes, positive baseline, firewall/IPv4/IPv6/TLS/proxy evidence |

Shared admission is global per Request Engine database. It does not implement a
per-account, per-IP or distributed ingress firewall. Retention scheduling remains
an explicit installation action. Mailbox verification records the operator's
assertion of an observed exact Message-ID; it does not query an inbox itself.
The restore tool records a declared outbound fence separately from independently
proven isolation. The network probe never interprets a TLS failure after a TCP
handshake as a blocked listener.

## Verification ledger

- Unit suite at this working checkpoint: `uv run pytest tests/unit -q -m
  'not postgres'`: **1311 passed, 1 skipped, 1 warning**. The skipped Docker Compose
  parser is unavailable locally; structural YAML and input rejection proofs ran.
  The warning is the existing Starlette TestClient/httpx deprecation.
- Shared admission: **11 PostgreSQL 18.6 tests**, including independent-connection
  contention, two real HTTP stacks, runtime LOGIN restrictions, lock failure,
  restart persistence and poisoned-role migration rollback; **43 unit tests**.
- Monitor projection and immutable definer closure: **8 PostgreSQL 18.6 tests**.
- Consolidated final admission/projection/privilege suites on a fresh PostgreSQL
  18.6 database: **19 passed**. Pending action age starts at the later of its
  execution time and retry time, so recently eligible work is not reported as
  overdue merely because its retry timestamp is old.
- SMTP/recovery tools: **75 focused unit tests**; their provider/receipt fixtures
  do not establish real external delivery or source-independent recovery.
- Retention renderer: **21 unit tests** and systemd calendar/unit verification.
- HTTP deployment renderer: **18 passed, 1 skipped** (Docker unavailable).
- Worker/telemetry/architecture focused proof: **14 passed**; OpenTelemetry SDK
  export smoke passed. Docker/promtool alert integration is delegated to its
  dedicated GitHub job and must pass before claiming that integration verified.
- Full observability and launcher tests: **60 passed**. The SDK smoke initially
  inherited the ambient one-percent trace sampler and failed its expected-span
  assertion. Its local provider now uses an explicit always-on sampler; the same
  smoke passed without changing the deployment's sampling configuration.
- Native same-cluster recovery proof: a custom dump restored into a blank database
  after dropping its source retained owners, ACL, forced RLS filtering and
  SECURITY DEFINER identity through a newly provisioned restricted LOGIN. This
  does not substitute for clean-host/off-host recovery evidence.

The first complete PostgreSQL runner attempt stopped at its principal-authority
packet: **499 passed, 1 failed**. Its database had applied the earlier metrics
function before the new due-age regression was added during integration. The
failure exposed the old retry-only age; a fresh database with the corrected
migration passed all 19 relevant tests. The complete runner is being repeated
against the stable implementation; the failed attempt remains failed evidence.

The canonical Python-quality lane and complete current-product PostgreSQL runner
are being rerun for the consolidated candidate. Earlier published source
`0ff371d13850f3a2501991b88add7b21b054542f` passed five workflows, but that result
does not certify this new implementation. No merge or deployment is claimed.

## Independent review and corrected candidate

The first consolidated Python-quality run completed all steps: **205 architecture,
1325 unit, 770 module tests**, with one Docker-dependent unit skip and the existing
deprecation warning. Exact checkpoint `f798abb136e54eb3c74a5fa32827e4fdc4437ed8`
also passed managed local publish certification in 194.455 seconds. The preceding
checkpoint's certification correctly failed because its Docker build context
omitted telemetry assets; that omission was fixed, not waived.

Three independent reviewers examined **41 validated quality-evidence/v2 packets**
for that checkpoint. Concrete findings led to these additional changes:

- Proxy header trust accepts only a single host IP (`/32` or `/128`), preventing
  trust inheritance by unrelated subnet hosts: **26 passed, 1 Docker skip**.
- Recovery certification validates the complete restore interval, including its
  start, within failure declaration and service recovery. A local restore-record
  validator keeps that evidence boundary explicit: **42 focused tests passed**.
- Metrics use an expression index and separate oldest-pending/expired-lease probes.
  Fresh PostgreSQL tests with 10,000 jobs verified the actual index plans and
  capped aggregate. Preflight now rejects poisoned column ACLs and current-database
  ownership/grantor dependencies: **5 projection tests passed**.
- Network endpoint schema validation has a local helper, retaining exact-address,
  TLS, bounded input and failure semantics: **14 tests passed**, Pyright clean.

The retention test-organization recommendation is deferred: its renderer and CLI
tests cover one protected-credential scheduling workflow and remain hermetic and
falsifiable. No concrete proof defect was found. This is a maintainability deferral,
not a waiver of a deterministic invariant. No human verdict is inferred from any
automated review. Updated exact-head packets, certification and full GitHub CI are
required for the corrected candidate; the earlier green certificate does not
authorize publication of a changed tree.
