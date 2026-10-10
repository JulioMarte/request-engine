# Operator alert acceptance

Status: deployment acceptance procedure, not executed production evidence.
Owner: the deployment operator. This guide completes gate O-07 in the
[readiness report](../testing/pr137-api-production-readiness-2026-10-06.md).

## Existing boundary and remaining implementation

The `operator-alerts` CI job runs a narrowly scoped observability fixture: pinned
Collector, Prometheus and Alertmanager containers validate the exact configs; an
OTLP emitter sends bounded worker/gauge samples; `promtool` evaluates the alert
fixtures; and a local webhook records firing and resolved statuses. This is a
specialized metrics-path proof, not a customer/business E2E suite. The containers
receive no Request Engine database URL, application credentials, HUMAN bearer, or
Docker socket access. Its allowlisted artifacts contain config/rule check output,
fixed metric names/labels, and only the fixture's firing/resolved status values.
The local HTTP 2xx proves transport to that test fixture, not external human
acknowledgement.

`GET /v1/platform/observability` requires a HUMAN actor with
`platform.readiness.read` on the private control plane. Its P7 measurements and
threshold alerts are advisory, process-local snapshots. They are not a queue of
notifications, durable incident history, or proof of operator receipt. Do not
publish that API or give a monitoring agent a human bearer credential to scrape
it. Deployment now provides a separate Collector Prometheus scrape endpoint,
Prometheus alert rules, and an Alertmanager webhook route. The route is unusable
until the operator replaces its `.invalid` placeholder with the operator-owned HTTPS
receiver. The local compose stack does not activate that receiver.

The central scheduled-action, outbox, and provider-event worker pools emit bounded
claims, cycles, outcomes, lease-loss, and processing-duration metrics when the pinned
OTel runtime is installed. An independent, read-only database poller emits capped
backlog/oldest-age and recent delivery failure/ambiguity metrics through a dedicated
login role. Backup/restore-evidence gauges still have no verified source; their rules
fire as missing/unknown rather than treating absence as health. This configuration
does not establish external receipt or acknowledgement. Use a dedicated monitoring service for
routing, grouping, deduplication and notifications; avoid placing network
notification calls inside business transactions or P7 metric observers.

P7 duration observations and thresholds must be finite, non-negative numbers.
Zero is valid; boolean, NaN, infinity and unrepresentable numbers are rejected
before replacing a signal. An absent recovery certification is `unknown` in
readiness: zero-valued initial telemetry alone must never imply a recent backup.
The monitoring rule must map `backup_evidence=unknown` or
`restore_drill=unknown` to an evidence-unverified alert after the agreed startup
grace. This means safety has not been demonstrated, not that data loss has
occurred. A missing or unreadable evidence source must not resolve that alert.
Counters reset on process restart. Observe every worker/process and detect
missing/stale exporters separately; a live API does not prove worker progress.

## Acceptance inputs

Record the candidate SHA/image digest, topology, process/replica inventory,
monitoring configuration revision, receiver/channel, responsible operator and
backup contact. Agree thresholds, evaluation windows and maximum receipt delay
before each trial; unapproved values are measurements only. Store references
to credentials, never token values. A receiver owned by the operator must be
available before conducting notification trials.

| Failure trial in an isolated acceptance environment | Required observation | Safe response |
| --- | --- | --- |
| Stop worker while creating legitimate queued work | Oldest-work age grows; heartbeat/progress missing | Inspect credentials/leases; resume one worker, verify backlog drains |
| Stall a worker past lease expiry | Lost/stale lease and stalled progress | Verify fencing before restarting; no duplicate external effect |
| Make SMTP unreachable, then simulate accepted-but-unacknowledged delivery | Delivery failure/backlog; ambiguous outcome separately visible | Reconcile ambiguous result; never blindly resend |
| Make OpenBao unavailable | Secret-store failures/readiness loss | Restore availability; verify governed resolution, never bypass policies |
| Exhaust the configured database pool | Timeout/error rate and backlog; independently running probes still observed | Measure aggregate connections; reduce load or adjust an approved budget |
| Repeated rejected authentication | Bounded rejection rate without identities/tokens in labels | Check shared ingress limits; keep valid users observable |
| Withhold a new backup or drill certification past approved age | Stale evidence alert; missing evidence is independently unhealthy | Execute verified backup/drill, then refresh operator-managed artifact |
| Start without a recovery certification | Evidence-unverified alert after approved startup grace; zero initial ages cannot suppress it | Supply a genuinely accepted artifact and verify the alert resolves |
| Stop Collector/exporter or monitoring evaluator | Missing telemetry/dead-man alert from independent monitoring | Restore monitoring; silence is not a healthy result |

Perform one reversible fault at a time. Use test identities and test delivery
destinations; never induce ambiguous mail to customers. Confirm the baseline
before injection, restore it afterwards and verify alert resolution.

## Receipt evidence and exit criteria

For every trial save UTC timestamps for injection, first observation, alert
evaluation, receiver receipt, operator acknowledgement and resolution. Include
the incident/reference ID, signal, approved threshold/window, receiver reference,
measured delay and resolution check. Keep payloads secret-free and redact
personal identifiers; preserve trace/span correlation by reference only.

The independent receiver record and acknowledgement are the receipt oracle.
An API alert, exporter success, HTTP 2xx from a webhook or SMTP acceptance alone
does not prove receipt by the responsible person. A sink trial may prove local
transport once implemented, but cannot substitute for real receiver acceptance.
Test grouping/deduplication, repeat escalation and receiver outages too.

O-07 remains pending if any required signal is missing, stale monitoring appears
healthy, notification transport is absent, receipt exceeds its agreed budget,
or no responsible operator acknowledges it. CI cannot close this gate without
that environment and independent evidence.
