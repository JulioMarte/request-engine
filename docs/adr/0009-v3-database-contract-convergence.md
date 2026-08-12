# 0009 — V3 database contract convergence
Status: Accepted

## Context

The executable V3 candidate and the pre-SQL contract diverged in three places before the first production baseline:

- `OfferingVersion` allowed `0..N` resource requirements in the catalog contract while authoritative Holds/Reservations already reject an empty claim set;
- the contract listed `Reservation.closed`, but the schema and implemented booking capabilities use only `confirmed` and `cancelled`;
- aggregate `revision` values were intended as concurrency tokens, but SQL only prevented them from moving backwards.

These are pre-baseline semantics, so preserving the inconsistency for compatibility would create accidental architecture.

## Decision

1. `OfferingVersion` may have zero resource requirements while catalog configuration is incomplete or non-booking. A V3 local-capacity Hold or Reservation requires at least one mandatory requirement and a complete active claim set.
2. V3 Reservation states are only `confirmed` and `cancelled`. There is no baseline `closed` state.
3. Capacity effect is temporal. A confirmed Reservation's active claim blocks commitment-sensitive Resource configuration only while its interval has not fully ended. Historical claims are preserved.
4. `OfferingResourceRequirement.quantity` and `CapacityClaim.quantity` mean capacity units on one selected concrete Resource, not a number of Resources to select.
5. Every UPDATE of a baseline row carrying an aggregate `revision` advances exactly one revision step. SQL may supply the step when the caller leaves revision unchanged, but skipped/backward values are rejected.
6. `Resource.availability_revision` remains a separate schedule/availability token.

This ADR supersedes ADR 0007 only where ADR 0007's `0..N` wording could be interpreted as allowing a zero-claim V3 booking. ADR 0007's remaining capacity-model decisions remain accepted.

## Consequences

Positive:

- contract, SQL behavior and current booking implementation converge before `0001_initial`;
- V3 cannot silently create capacity-free local Reservations;
- completed-in-time historical appointments do not permanently freeze Resource maintenance;
- no fulfillment/execution lifecycle is smuggled into Reservation merely to solve temporal capacity;
- revision tokens become deterministic DB-backed concurrency evidence;
- quantity semantics remain deliberately small and do not imply pools or cardinality expressions.

Trade-offs:

- a catalog version can temporarily have `bookable=true` while still being operationally incomplete; commitment creation remains the authoritative gate;
- external-capacity or intentionally capacity-free appointments need a future explicit capability/model instead of exploiting zero requirements;
- callers must treat revision as opaque because one command can perform multiple authoritative row updates and therefore advance more than one step overall.

## Rejected alternatives

### Add `Reservation.closed`

Rejected because V3 has no baseline fulfillment/session aggregate and historical capacity can be handled using interval semantics without conflating execution with booking state.

### Require resource requirements at OfferingVersion INSERT commit

Rejected because the parent and immutable child configuration may be assembled in separate catalog operations. The hard invariant belongs at the first authoritative capacity commitment boundary.

### Allow zero-claim Reservations

Rejected because a successful V3 appointment currently means locally committed capacity. External capacity commitments are explicitly deferred.

### Treat quantity as resource cardinality

Rejected because it immediately requires optimizer/pool/OR semantics that V3 intentionally excludes.

### Permit arbitrary revision jumps

Rejected because it weakens the revision token as concurrency evidence and makes stale-write behavior harder to reason about.