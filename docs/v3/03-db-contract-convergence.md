# Request Engine V3 — database contract convergence

> **Status:** normative pre-baseline amendment.
>
> This document narrows and corrects specific clauses in `02-pre-sql-contract.md` while the V3 candidate is still pre-production. For the decisions listed below, this document has precedence over conflicting wording in `02-pre-sql-contract.md` and ADR 0007. Before `0001_initial` is frozen, these decisions must be folded back into the canonical contract so the baseline has one non-contradictory source of truth.

---

# 1. Why this amendment exists

The first executable V3 candidate exposed three semantic mismatches that must be resolved before the schema can be frozen:

1. the contract allowed `0..N` resource requirements while live Holds/Reservations already require a complete, non-empty claim set;
2. the contract mentioned a `closed` Reservation state that the SQL schema and implemented booking capabilities do not use;
3. revision columns were treated as concurrency tokens by application code, but the database only rejected revisions that moved backwards.

The goal is convergence, not another domain redesign.

---

# 2. OfferingVersion and local capacity requirements

An `OfferingVersion` may contain `0..N` `OfferingResourceRequirement` rows as catalog configuration.

However, V3 appointment booking is explicitly a **local-capacity commitment capability**. Therefore an OfferingVersion is operationally eligible for `CapacityHold` or `Reservation` creation only when it has `1..N` mandatory resource requirements.

Consequences:

```text
requestable/non-booking OfferingVersion
    -> may have zero local resource requirements

bookable flag with zero requirements
    -> incomplete booking configuration
    -> no live CapacityHold may commit
    -> no confirmed Reservation may commit

successful Hold/Reservation
    -> exactly one active CapacityClaim per mandatory requirement
```

The database enforces this at the authoritative commitment boundary through deferred Hold/Reservation claim-completeness checks. This intentionally allows catalog configuration to be assembled before it becomes usable for booking.

A future capability that books externally controlled or capacity-free appointments is **not** silently represented as a zero-claim Reservation. It requires an explicit contract/migration because external capacity commitments are outside the V3 baseline.

Affected invariants: `V3-I19`, `V3-I21`.

---

# 3. ResourceRequirement quantity semantics

For the V3 baseline, `OfferingResourceRequirement.quantity` means:

> capacity units consumed on the **one concrete Resource selected for that requirement** during the appointment interval.

It does **not** mean:

```text
number of Resources to select
number of interchangeable providers
k-of-n cardinality
resource pool size
```

Examples:

```text
exclusive doctor requirement, quantity=1
    -> one doctor Resource, one exclusive unit

room Resource with capacity_model=units, capacity_units=10,
requirement quantity=3
    -> one room Resource consumes three of its ten units
```

Each `CapacityClaim.quantity` must equal its requirement quantity. Multiple mandatory requirements are ANDed. The existing column name is retained for the pre-baseline candidate; a rename is not required to express a new concept.

Affected invariants: `V3-I17`, `V3-I18`, `V3-I21`.

---

# 4. Reservation lifecycle

The V3 baseline Reservation lifecycle is exactly:

```text
confirmed
cancelled
```

There is no baseline `closed` Reservation state.

Rationale:

- V3 explicitly defers `ServiceSession` / fulfillment accounting;
- attendance, queue completion and no-show semantics are separate facts/lifecycles;
- adding `closed` only to make old appointments stop blocking capacity would conflate lifecycle with temporal capacity effect;
- a confirmed historical appointment remains useful as the durable fact that the booking existed and was never cancelled.

A Reservation consumes local capacity iff all of the following are true for a claim at the authoritative instant being evaluated:

```text
claim.status = active
AND reservation.status = confirmed
AND the claim interval is temporally relevant to the operation
```

For overlap validation, temporal relevance is naturally expressed by range overlap.

For commitment-sensitive Resource configuration changes, a confirmed Reservation claim is a blocking live commitment only while:

```text
upper(claim.during) > authoritative DB wall clock
```

Therefore a confirmed Reservation whose interval has fully ended does not permanently prevent Resource deactivation/location/capacity maintenance. Its historical claim is preserved; history is not rewritten merely because wall-clock time advanced.

Cancellation remains the only baseline Reservation terminal transition and must atomically release active Reservation claims.

Affected invariants: `V3-I17`, `V3-I18`, `V3-I23`, `V3-I28`.

---

# 5. Revision semantics

Revision is an opaque optimistic-concurrency token, not a business sequence number.

For every V3 aggregate row that owns a `revision` column:

```text
INSERT -> revision = 1
Every authoritative UPDATE -> next revision = previous revision + 1
```

The database may supply the `+1` when a trusted caller leaves the previous revision value unchanged, but it rejects skipped, decreased or otherwise non-canonical revision changes.

This applies to:

```text
Representation
Request
CapacityHold
Reservation
ServiceQueue
QueueEntry
WaitlistEntry
SlotOpportunity
SlotOffer
CommunicationTask
ReminderPlan
```

`Resource.availability_revision` is deliberately separate. It advances when schedule/exception availability changes and is not governed by this generic aggregate revision rule.

A command may perform more than one authoritative row UPDATE while holding the same aggregate lock; each UPDATE advances the token. Consumers must treat revision as opaque and compare equality, never infer business meaning from the numeric distance between revisions.

### V3-I62 — Canonical aggregate revision advancement

Every authoritative UPDATE of a row with a baseline aggregate `revision` advances that row from `N` to exactly `N+1`; skipped/backward revisions are rejected.

Owner: `DB` with application optimistic-concurrency semantics layered above it.

---

# 6. Freeze consequences

The V3 candidate is not eligible for `0001_initial` until PostgreSQL-backed tests prove at minimum:

- zero-requirement OfferingVersions cannot produce a live Hold or confirmed Reservation;
- a past confirmed Reservation does not act as a permanent live Resource commitment;
- a current/future confirmed Reservation still blocks commitment-sensitive Resource mutation;
- `closed` is not an accepted Reservation state;
- revision-managed aggregates cannot skip or move revision backwards;
- existing booking/capacity race tests remain green.

These are schema/transaction contract properties. Python API surface cleanup comes later.