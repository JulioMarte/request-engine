# Request Engine — F4 Deterministic Projection Baseline

Status: **normative implementation amendment for `feature/live-capacity-projection`**.

Parent contract: `29-live-capacity-projection-contract.md`.

This document freezes implementation choices intentionally left open by the parent F4 contract. It does not change workload identity, Booking authority or configured policy.

## Historical estimator baseline

For one workload classification:

```text
history lookback boundary: 90 days before observed_at
maximum samples per tier: 64 most recent eligible observations
minimum samples per tier: 5
sample eligibility: completed ServiceSession, positive active_service_seconds,
                    non-null actual workload matching the requested classification
Resource tier: same tenant + same Resource + matching actual workload
Tenant tier: same tenant + matching actual workload, regardless of Resource
statistic: median active_service_seconds
rounding: integer seconds; even-sample median rounds .5 seconds upward
outlier policy: no destructive trimming in F4 baseline; median provides robustness
```

The database reader MUST impose the lookback and sample bound before returning history. It MUST NOT perform an unbounded tenant-history scan and then truncate in Python.

## Fallback order

```text
>= 5 eligible Resource observations
  -> Resource median
else >= 5 eligible tenant observations
  -> tenant median
else positive configured workload-estimate policy
  -> configured estimate
else positive applicable planned/contextual duration
  -> planned fallback
else
  -> unknown
```

An observation selected for the Resource tier may also satisfy the broader tenant population, but Resource sufficiency is evaluated first. Tenant fallback is consulted only when the Resource tier is insufficient.

Historical evidence never writes back to configured workload-estimate policy. The projection result records estimate source and historical sample count.

## Initial Resource execution model

The initial F4 projection is a single sequential service timeline. Therefore an active projection scope is valid only when the configured Resource is:

```text
capacity_model = exclusive
capacity_units = 1
```

A parallel/unit-capacity Resource is not silently flattened into one timeline. Initial F4 reports the scope as invalid configuration instead of publishing a false sequential ETA. Supporting parallel unit capacity requires an explicit later projection contract and evidence.

This restriction does not alter Booking capacity semantics. Booking remains authoritative for Resources using `units`; F4 simply declines to project a model it cannot yet represent faithfully.

## Commitment treatment

F4 keeps planning commitments and projected workload separate so the same Reservation is not consumed twice:

```text
confirmed Reservation + active Reservation-backed CapacityClaim
  -> future same-day Reservation contributes planned workload

Reservation represented by QueueEntry/ServiceSession
  -> live representation wins through F4 deduplication

active CapacityHold / claim without Reservation
  -> remains an opaque Booking commitment and removes the affected interval
```

Reservation-backed claims are not also removed from the operational interval before the Reservation workload is projected. This preserves Booking authority without double-counting the same planned service.

## Temporal and provenance requirements

`observed_at` is PostgreSQL-sourced and the 90-day boundary is evaluated relative to that same projection observation instant. Completed sessions after `observed_at` are ineligible even if a caller supplies them accidentally.

The historical adapter orders eligible observations newest-first before applying the 64-row limit. Ties use stable ServiceSession identity so the bounded population is deterministic.

The same-day projection horizon ends at the next local midnight of the configured active Location, resolved through Booking timezone rules. F4 does not define "today" as UTC midnight or `observed_at + 24 hours`.

## Required evidence

Tests must falsify at least:

- Resource history incorrectly losing to tenant history;
- fewer than five observations being treated as sufficient;
- more than 64 observations changing the selected bounded population;
- wall-clock duration being used instead of `active_service_seconds`;
- a different actual workload contaminating the sample;
- history outside the 90-day boundary contaminating the sample;
- historical estimation mutating configured policy;
- insufficient history fabricating an estimate instead of following fallback order;
- Reservation-backed capacity being counted once as an interval block and again as workload;
- an active non-Reservation hold failing to reduce effective projection intervals;
- a `units` or multi-unit Resource being projected as one sequential Resource;
- UTC midnight being used instead of the configured Location local-day horizon.
