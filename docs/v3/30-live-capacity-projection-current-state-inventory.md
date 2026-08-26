# Request Engine — F4 Live Capacity Projection Current-State Inventory

Status: **implemented hardening / closure pending exact-remote local verification** on `feature/live-capacity-projection`.

Normative target: `29-live-capacity-projection-contract.md`.

This document records the implemented F4 disposition against the integrated F3 baseline. It is no longer an implementation-planning document. F4 is materially built; the remaining release gate is executable local evidence at the exact remote HEAD plus correction of any failures that evidence exposes.

## 1. Authority boundary

F4 is an advisory/read-model bounded context. It consumes authoritative Booking, Queue and Delivery facts through published narrow contracts and does not become authority for any of them.

```text
Booking owns Reservation / CapacityClaim / schedule and contextual planning truth.
Queue owns QueueEntry and queue lifecycle truth.
Delivery owns ServiceSession / interruption / ResourceActivity truth.
live_capacity owns projection configuration and deterministic advisory derivation.
```

Projection reads and intake evaluation do not create/release CapacityClaims, rewrite Reservations, mutate QueueEntries/ServiceSessions, or persist ETA/headroom as authoritative counters.

## 2. Implemented old -> new disposition

| Existing/new surface | Disposition | Implemented F4 treatment |
|---|---|---|
| `Reservation` | KEEP + CONSUME | Same-day future planning workload and planned-duration fallback; never rewritten by F4. |
| `CapacityClaim` | KEEP + CONSUME | Remains commitment/capacity authority; F4 never creates/releases claims. |
| effective Resource/Location availability | KEEP + CONSUME | Booking composes the authoritative remaining operational intervals. |
| contextual Offering duration | KEEP + FALLBACK | Applicable planned duration is the last known fallback before `unknown`. |
| `ServiceQueue` | KEEP + CONSUME | Explicit projection scope includes Queue + Resource + Location. |
| `QueueEntry` | KEEP + CONSUME | Waiting/called/serving representation, ordering and expected workload. |
| completed reservation-backed QueueEntry | KEEP + CONSUME NARROW FACT | Used only to prevent a completed-early service from reappearing as unfinished live Reservation workload. |
| `ServiceSession` | KEEP + CONSUME | Active execution supersedes QueueEntry for remaining workload; completed sessions feed bounded history. |
| `ServiceSessionInterruption` | KEEP + CONSUME | Closed time is excluded from productive duration; open interruption makes projection indeterminate. |
| `ResourceActivity` | KEEP + CONSUME | Open-ended occupation makes projection indeterminate rather than inventing an end. |
| workload-estimate policy | ADD | Separate revisioned/idempotent F4 configuration with audit/outbox semantics. |
| projection-scope policy | ADD | Explicit Queue + Resource + Location baseline mapping. |
| `live_capacity` bounded context | ADD | Owns projection semantics/configuration/read contracts only. |
| persisted queue position / ETA / live counter | REJECT | Derived on read. |
| automatic policy learning | REJECT | History informs estimates but does not silently mutate policy. |
| stop-intake automation / recovery / delay communications | DEFER F5 | F4 evaluates and explains; it does not execute recovery policy. |

## 3. Published source contracts

F4 consumes only supported module contracts:

```text
booking.contracts.live_capacity
queue.contracts.live_capacity
delivery.contracts.live_capacity
```

### Booking

Publishes one coherent operational-availability snapshot containing the configured Resource/Location scope, remaining effective intervals and same-day planned Reservation workload.

Booking remains responsible for schedule, Location, assignment, exception and capacity-claim composition. F4 does not reimplement F1 availability logic.

### Queue

Publishes active projection entries without customer presentation data. For the finite set of same-day planned Reservation IDs supplied by the composition layer, Queue also publishes which of those Reservations already have a completed QueueEntry. This bounded terminal fact is necessary because F3 intentionally preserves Reservation planning truth after actual service completes.

### Delivery

Publishes active Resource execution/occupation and bounded completed ServiceSession duration observations. Historical productive duration excludes closed interruption time.

## 4. Workload estimate policy

Implemented deterministic precedence:

```text
same Resource + actual workload history
-> tenant workload history
-> configured workload-estimate policy
-> applicable planned Reservation duration
-> unknown
```

History is bounded/deterministic and does not mutate configured policy. Unknown is represented explicitly; it is never converted to zero or an arbitrary average.

When a Reservation has already checked in, its planned duration follows the QueueEntry or active ServiceSession that wins deduplication as estimate provenance only. The Reservation itself is not retained as a second live work item.

## 5. Remaining-work deduplication

Implemented precedence:

```text
active ServiceSession > QueueEntry > Reservation
```

Important terminal rule:

```text
completed reservation-backed QueueEntry
    -> Reservation remains visible to scheduled planning truth
    -> Reservation contributes zero unfinished live workload
```

This rule closes the early-completion case where a confirmed future Reservation would otherwise reappear after its QueueEntry/ServiceSession became terminal.

## 6. Scheduled capacity versus live intake capacity

F4 now preserves the contractually required distinction explicitly.

Staff projection exposes:

```text
scheduled_committed_workload_seconds
scheduled_headroom_seconds
projected_remaining_workload_seconds
live_intake_headroom_seconds
live_vs_scheduled_headroom_delta_seconds
```

`live_headroom_seconds` remains a compatibility alias for `live_intake_headroom_seconds`.

The delta is:

```text
live_intake_headroom_seconds - scheduled_headroom_seconds
```

Negative means live reality is consuming more projected work than scheduled commitments alone imply. Positive means live operations are ahead of the still-preserved planning view. Neither value changes Booking authority.

## 7. Temporal projection behavior

The projection engine:

- obtains one PostgreSQL-sourced `observed_at`;
- composes Booking, Queue and Delivery inside one coherent read snapshot;
- projects sequentially over possibly discontinuous remaining effective intervals;
- subtracts elapsed productive time from the current ServiceSession estimate;
- excludes closed interruption duration from productive historical evidence;
- returns explicit `indeterminate` state for open ServiceSession interruption or open ResourceActivity;
- does not take mutation/capacity ownership merely to read advisory state.

## 8. API surfaces

Implemented independently typed surfaces:

```text
staff live-capacity projection
read-only intake evaluation
customer-safe queue projection
```

The customer DTO is not produced by serializing the staff DTO and deleting fields. It exposes only approved self-relative projection data and does not disclose other customers, workload classifications, operational causes or historical samples.

## 9. Persistence and security

F4 migration lineage follows the actual integrated F3 head:

```text
0006_f3_fact_hardening
-> 0007_live_capacity
```

F4 configuration tables include revision/idempotency behavior, RLS/FORCE RLS and least-privilege evidence. Existing PostgreSQL evidence covers projection-scope/workload-policy revision races, validation, RLS, customer authority/snapshot semantics and historical-duration source behavior.

## 10. Durable guarantees

The normative current guarantee inventory now includes:

```text
INV-LIVE-CAPACITY-SEPARATION-001
INV-LIVE-CAPACITY-PROJECTION-001
INV-LIVE-CAPACITY-WORKLOAD-001
INV-LIVE-CAPACITY-TEMPORAL-001
INV-LIVE-CAPACITY-DEDUP-001
INV-LIVE-CAPACITY-PRIVACY-001
```

Representative evidence is reconciled in `docs/testing/current-proof-map.toml`. The guarantee inventory is normative; the proof map remains updateable evidence mapping rather than an immutable filename snapshot.

## 11. Acceptance evidence

`tests/e2e/test_f4_live_capacity_journey.py` remains the focused staff/intake/customer read-only/privacy journey.

`tests/e2e/test_f4_operational_day_acceptance.py` composes the operational-day behavior that the original smoke journey did not prove:

```text
two future same-day Reservations
-> first Reservation check-in with no configured estimate
-> planned-duration fallback transfers to QueueEntry
-> additional walk-in with configured workload estimate
-> scheduled and live headroom diverge explicitly
-> CallNext
-> active ServiceSession supersedes QueueEntry
-> open interruption makes projection indeterminate
-> resume restores calculable projection
-> completion recomputes live workload
-> completed-early Reservation does not reappear live
-> scheduled planning truth remains preserved
-> Reservation and CapacityClaim durable state remain unchanged by projection reads/service composition
```

Historical estimator bounds/source, discontinuous interval projection, elapsed-current-service semantics, open ResourceActivity uncertainty, customer authority and RLS remain covered by narrower DB/module evidence where those guarantees are more directly falsifiable than by one oversized E2E scenario.

## 12. Local exact-head closure runner

GitHub Actions is not the closure authority for this branch. Use:

```bash
bash scripts/ci/run_f4_local_closure.sh
```

The runner deliberately:

1. requires a checked-out branch;
2. refuses a dirty working tree so forced synchronization cannot silently destroy local work;
3. fetches current remote refs;
4. force-synchronizes the clean local branch to `origin/<current-branch>` with `git reset --hard`;
5. verifies exact local/remote SHA equality and cleanliness;
6. runs the Python quality/architecture/unit/module lane with file-budget comparison against `origin/development` by default;
7. runs the canonical current-product PostgreSQL/integration/E2E proof.

`FILE_BUDGET_BASE_REF` may be supplied explicitly when intentionally validating against another integration base.

## 13. Remaining closure gate

Do **not** call F4 merge-ready solely from repository inspection.

The current branch must still produce a completely green local exact-remote closure run. Any failures from that run are blockers until understood and corrected. PR #80 therefore remains Draft.

Once the local run is green, perform one final adversarial review of:

```text
planning vs live separation
completed-early service suppression
dedup and fallback provenance
single-snapshot temporal semantics
customer privacy / tenant opacity
configuration races
projection read no-authority/no-lock behavior
migration bootstrap and upgrade lineage
```

Only then is F4 eligible to leave Draft and merge.
