# Request Engine — F2 Discovery Adversarial Hardening

Status: **historical adversarial-review provenance** for `feature/geospatial-cross-tenant-discovery`.

This document records defects found while hardening the first F2 implementation and explains why several final rules exist. It is **not normative** and has no precedence over `24-geospatial-cross-tenant-discovery-contract.md`. All closed decisions from this review have been consolidated into document 24.

Use this file when reconstructing design history. Implement and review current F2 behavior from document 24 plus the current guarantee/proof inventories.

## 1. Trust-boundary correction

The first implementation combined too much authority in the discovery process:

```text
Discovery process
  + request_engine_app SessionFactory
  + cross-tenant SECURITY DEFINER function
  + normal Booking appointment-option signing key
```

It also emitted decodable Booking option tokens containing concrete Resource/assignment identifiers. That violated hidden-provider privacy.

The corrected design introduced:

```text
request_engine_discovery NOLOGIN NOBYPASSRLS
narrow candidate/handoff functions only
no generic tenant table authority
opaque discoopt_v1
server-side DiscoveryBookingHandoff state
```

## 2. Commitment-time fence

The review rejected a two-transaction protocol where publication was validated and committed before Booking. Final F2 revalidates Publication and Mapping inside the same authoritative Booking commitment transaction that applies the existing F1 schedule/terms/assignment/capacity checks.

This closes the discovery-to-booking TOCTOU window.

## 3. Handoff lifecycle

The review established:

```text
same command + same Idempotency-Key
  -> safe replay of prior committed Reservation

same consumed handoff + different mutation
  -> stale/rejected
  -> no second Reservation/CapacityClaim
```

It also added a current OfferingVersion fence so a newly published version invalidates an older discovery handoff.

## 4. Provider privacy and later product completion

The first hardening pass deliberately refused to expose concrete provider identity because no accepted public Resource projection existed yet. That was the correct privacy decision at the time, but it reduced the original F2 product goal.

The final contract subsequently closes that product gap with `ResourcePublicProfile`:

```text
public display name
optional public role/title/specialty label
optional public profile image/reference
```

and a tenant-authorized `operations.manage_discovery` command to maintain it.

Final semantics are now:

```text
provider_visibility=hidden
  -> no concrete provider projection

provider_visibility=public
  -> resource-specific publication required
  -> active ResourcePublicProfile required
  -> only approved public provider fields emitted
```

GlobalIdentity, SharedCapacityIdentity, private Resource fields and assignment identifiers remain private.

## 5. Public Location and data minimization follow-up

The final F2 reconciliation also closed two gaps not solved by the first hardening pass:

- Location public address fields are projected from F1 operational Location truth so the result can answer "where";
- relational UUIDs such as `organization_id`, `offering_id`, `offering_version_id`, `location_id` and `resource_id` are no longer emitted by the public discovery DTO. Public keys form the initial external identity contract.

## 6. Mapping provenance

The hardening review changed Offering classification replacement from in-place semantic mutation to monotonic provenance:

```text
lock Offering
revoke old mapping
insert new mapping
append audit
```

It also removed tenant runtime global taxonomy enumeration and retained only narrow active-key lookup.

## 7. Publication scope serialization

The review established immutable publication scope, monotonic revocation and the rule that broad and resource-specific publications for one Organization + Offering + Location cannot overlap.

The final implementation serializes the mixed-scope check with a transaction advisory lock plus overlap predicate and has a real PostgreSQL winner/loser/final-state race proof.

## 8. Ranking and bounded exhaustive search

The first implementation risked selecting nearest candidates before knowing appointment ordering. Final F2 instead evaluates every eligible candidate up to the safe bound and globally sorts:

```text
1 earliest appointment start
2 distance
3 stable IDs as internal deterministic tie-breakers
```

Candidate 201 returns an explicit too-broad failure instead of a silently partial result.

A future batched slot reader may improve latency only if behavior remains equivalent.

## 9. Evidence gaps found after the first hardening pass

A later literal comparison against the F2 Definition of Done found that general operational tests were being mistaken for F2-specific evidence. The final reconciliation therefore added direct proofs for:

```text
operations.manage_discovery authority
idempotent/conflicting replay
foreign-vs-unknown mutation opacity
no partial durable state on rejection
taxonomy lifecycle/audit
mapping concurrent-first race
broad-vs-specific publication race
inclusive geospatial boundary
revoked publication invisibility
public provider/location projection
discoopt_v1 stale after schedule change
discoopt_v1 stale after commercial terms change
discoopt_v1 stale after assignment retirement
consumed-handoff safe replay/new-mutation rejection
```

F2 guarantees are now represented in `docs/testing/current-guarantees.toml` and representative proofs in `docs/testing/current-proof-map.toml`.

## 10. Migration provenance

F2 was developed through provisional SQL-bearing steps under `migrations/f2_steps/`. Because it had not been deployed and Request Engine remains pre-customer/pre-production, those steps are executed by one consolidated production Alembic revision:

```text
0004_geospatial_cross_tenant_discovery
```

This preserves useful development provenance without pretending known-intermediate F2 DDL was independently deployed production history. Released V3 and integrated F1 migrations remain untouched.

## 11. Precedence

Current precedence for F2 is:

```text
docs/v3/24-geospatial-cross-tenant-discovery-contract.md
  > current F2 implementation/evidence
  > this historical review record
```

If this document conflicts with document 24, document 24 wins.