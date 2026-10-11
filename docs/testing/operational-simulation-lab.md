# Operational simulation laboratory

This laboratory tests mechanisms with real sockets, TLS, PostgreSQL 18 and
separate service processes. Provider policies and infrastructure are controlled
fixtures. It is evidence about this candidate and this topology, not acceptance
of a production installation.

## Proof obligations

| Risk | Execution boundary | Independent oracle | Defect that must fail |
| --- | --- | --- | --- |
| SMTP authentication and transport | Actual STARTTLS/AUTH against the programmable SMTP service | Provider attempt/receipt API and exact Message-ID | Wrong credentials accepted, unverified TLS, or missing receipt |
| SMTP uncertain delivery | Provider accepts DATA and drops the final reply | Exact Message-ID retains one receipt/attempt after replay and a distinct governed delivery completes with its own receipt | Blind resend during observed worker progress or incorrectly claiming a definitive rejection |
| Definite SMTP rejection | Provider returns 451 or 550 without accepting DATA | No accepted message; production result classification | Temporary rejection treated as ambiguous, or permanent rejection retried blindly |
| Global authentication admission | Two API processes use one PostgreSQL admission state; one process restarts | HTTP 200/429 plus outer read-only SQL state | Independent per-process budgets, reset on restart, or sessions created by rejected calls |
| Container network boundary | Public and private probe containers on distinct ingress networks | Same live IP/port reachable privately and refused, timed out or explicitly without route publicly | Public TCP access to PostgreSQL, OpenBao or control plane |
| TLS ingress | Dedicated HTTPS gateways and ephemeral CA | Client certificate-chain and hostname verification | Invalid chain/name accepted, or HTTPS failure counted as isolation success |
| Encrypted external backup | Real recovery CLI uploads to an authenticated HTTPS storage service | New client download after source containers/volumes and original local backup are destroyed | Hidden source dependence, unauthenticated download, tampered ciphertext accepted |
| Clean recovery | Real CLI restores downloaded PostgreSQL archive and OpenBao Raft snapshot | Restored marker, ownership/ACL/RLS/function catalog and independent secret lookup | Lost facts, privileges changed, or original volume reused |
| Alert causality and recovery | Real worker failure, SQL collector, Prometheus rule, Alertmanager and receiver | Receiver records firing and resolved notifications; worker final outcomes | Synthetic alert injection substitutes for the rule path, or recovery fails to clear the signal |
| Receiver outage | Receiver returns HTTP 503 before accepting notifications | Rejected request followed by actual Alertmanager retry | Failed notification silently disappears |
| Monitor failure | Stop SQL collector, OTel Collector, Prometheus and Alertmanager separately | Rules and receiver for collectors; separate host probe checks the current Prometheus Watchdog and freshness of the receiver's last accepted Watchdog | Failed monitor reports itself healthy or lost notification delivery remains invisible |

## Execution and isolation

Ordinary business journeys remain HTTP-only consumers of the reusable Docker
E2E platform. `smtp-provider-lab` is an ordinary registered suite: foundations
and governed recovery are created through public contracts. It receives no
database login, Docker socket or application internals. See
[SMTP provider lab](smtp-provider-lab.md).

`network-auth-admission` declares the specialized `network-boundary` driver.
The outer administrator installs/migrates the fresh world, obtains actual
container IPs, restarts a replica, and reads aggregate authoritative admission
state. The public probe has only public ingress access. The private probe has
private ingress and backend connectivity solely to establish live TCP controls;
neither probe receives database credentials or Docker authority. The ordinary
runner's existing isolation proof also runs. Unknown drivers fail closed.

The off-host restore and monitoring scripts are infrastructure exceptions: the
outer administrator needs lifecycle/database authority to destroy disposable
source volumes, create targets or inject actual service failures. They do not
grant that authority to a normal black-box runner. Monitoring fixture setup and
administrative replay are distinct from the restricted worker and collector
connections. These probes do not certify business capability authorization.
Before fault injection, monitoring requires the collector's successful database
read timestamp to reach Prometheus through OTLP and a real scrape. Its permission
verification runs as the actual aggregate-only login; privileged catalog checks
alone cannot prove that the collector can start.

The monitoring worker receives only its restricted runtime database login. The
outer host creates the disposable event and administratively replays it before
signalling recovery. The worker checks that its login cannot insert provider
events directly, replay them administratively or exercise installation authority.
The independent host Watchdog probe requires both a currently firing rule and a
recent Watchdog accepted by the receiver. Stopping Alertmanager must make that
receipt stale while Prometheus remains available; restarting it must produce a
fresh receipt. A dedicated laboratory route repeats Watchdog every five seconds,
without changing the production routing file. Waiters inspect the latest probe
state, so an earlier successful state cannot satisfy recovery.
The laboratory also sets Prometheus alert resend delay to five seconds, so an
Alertmanager restart can receive active alerts on the next rule-group evaluation.
The receiver freshness bound remains fifteen seconds and restart recovery must
arrive within sixty seconds. These accelerated test settings do not certify
production notification timing.

TLS credentials are created outside artifact directories and removed during
cleanup. Only the owning server receives its leaf private key. Clients receive
the CA certificate; the CA private key is never mounted into a service. Normal
runner credential handoff is a sibling directory, so it cannot read TLS keys.
No reusable production credential is used. Logs and evidence remain sanitized.

```bash
bash scripts/ci/run_e2e_platform.sh all
bash scripts/ci/run_e2e_suite.sh smtp-provider-lab
bash scripts/ci/run_e2e_suite.sh network-auth-admission
bash scripts/ci/offhost_recovery_restore_smoke.sh .ci/offhost-recovery.json
bash scripts/ci/operator_alerts_smoke.sh
```

The registry selects the SMTP and network suites on PRs. P7 recovery owns the
off-host restoration proof. P7 configuration owns focused SMTP socket acceptance
and actual monitoring-path smoke. Exact-source GitHub workflow results are the
execution evidence; adding these scripts alone is not a passing result.

## Honest limits

* The storage service is an HTTPS fixture, not an S3 compatibility, cloud
  durability, object-lock, lifecycle or multi-region proof.
* SMTP acceptance is acceptance by the fixture. Internet routing, real mailbox
  delivery, SPF/DKIM/DMARC, reputation and provider throttling remain unproved.
* Docker IPv4 bridge isolation and lab certificates do not establish deployed
  firewall, IPv6, DNS, ingress, renewal or host security correctness.
* A local HTTP receiver acknowledgement is not an external operator's
  acknowledgement. The host Watchdog probe is independent of Prometheus but
  shares the CI host; host/site failure detection needs an external monitor.
* Restored markers prove recoverability of the tested snapshot. They do not
  establish production RPO/RTO, unseal-key custody, HA or operational acceptance.
* Bounded HTTP load tooling and retention CLI/timer renderer have their own
  proofs. These functional lab scenarios do not establish production-shaped
  throughput, host resource capacity or installation of a systemd timer.
