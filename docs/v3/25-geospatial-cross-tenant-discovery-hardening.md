# Request Engine — F2 Discovery Adversarial Hardening

Status: historical adversarial-review provenance for `feature/geospatial-cross-tenant-discovery`; all accepted corrections are consolidated into document 24.

This document records design corrections found during adversarial review of the first F2 implementation. It no longer has normative precedence. The authoritative F2 contract is `24-geospatial-cross-tenant-discovery-contract.md`.

## 1. Why the first implementation was insufficient

The first implementation correctly introduced explicit publication and a separate platform-facing HTTP app, but it accidentally accumulated authority in that process:

```text
Discovery process
  + request_engine_app SessionFactory
  + cross-tenant SECURITY DEFINER function
  + normal Booking appointment-option signing key
```

It also emitted normal `aptopt_v2` tokens. Those tokens are integrity protected but not encrypted and contain concrete Resource/assignment identifiers. Therefore `provider_visibility=hidden` was not actually private, and publication/mapping provenance disappeared before Booking revalidation.

A green CI run would not make those trust-boundary defects acceptable.

## 2. Corrected process authority

The public Discovery process is now composed only from narrow ports:

```text
DiscoveryCandidateReader
PublishedSlotReader
DiscoveryHandoffIssuer
PlatformDiscoveryActorResolver
```

It must not receive:

```text
request_engine_app generic SessionFactory
request_engine_admin credentials
normal Booking appointment-option signing key
arbitrary cross-tenant relation access
```

PostgreSQL introduces a dedicated runtime grant role:

```text
request_engine_discovery
  NOLOGIN
  NOBYPASSRLS
```

Deployment credentials may inherit that role, but F2 runtime authority is limited to EXECUTE on the exact protected candidate/handoff functions. The role receives no generic tenant table DML/SELECT.

Privileged cross-tenant function bodies remain owned by the existing trusted admin boundary rather than turning the runtime role into a bypass role.

## 3. Opaque `discoopt_v1`

F2 no longer returns a normal Booking `aptopt_v1/v2` token.

The public token is:

```text
discoopt_v1.<cryptographically-random-secret>
```

Only the SHA-256 token hash is persisted. The concrete selection stays server-side in `DiscoveryBookingHandoff` state:

```text
Organization
Publication id + observed revision
Mapping id + observed revision
OfferingVersion
Location
concrete Booking Resource selection
start/end
commercial/configuration observations
expiry
consumed Reservation provenance
```

The token therefore does not serialize Resource IDs, assignment IDs, GlobalIdentity or SharedCapacityIdentity. Random bearer entropy provides lookup capability; authoritative integrity comes from server-side state and relational constraints rather than caller-controlled token contents.

## 4. Discovery-to-Booking transaction fence

A handoff is advisory until normal tenant Booking executes.

`appointments.book` still requires ordinary Booking capability/subject authority. When the supplied option is `discoopt_v1`, Booking:

1. hashes and resolves it under the caller Organization;
2. reconstructs the internal Booking option from server-side state;
3. installs only the handoff UUID as task-local execution context;
4. opens the normal tenant Booking transaction;
5. propagates the UUID transaction-locally to PostgreSQL;
6. Reservation INSERT trigger locks/revalidates the exact Mapping and Publication observations;
7. Booking performs its existing F1 schedule/terms/Resource/capacity revalidation;
8. the same transaction commits Reservation/CapacityClaim/commercial provenance and marks the handoff consumed.

Therefore this unsafe protocol is explicitly rejected:

```text
validate publication
COMMIT
<revoke can win here>
book
COMMIT
```

Publication/mapping validation is part of the commitment transaction, closing the TOCTOU window.

## 5. Handoff lifecycle and idempotency

A fresh handoff is short-lived and single-commit-use.

After a Reservation consumes it:

```text
same HTTP command + same Idempotency-Key
  -> may resolve the already-consumed handoff
  -> Booking idempotency returns the prior semantic result before another INSERT

same handoff + different new mutation
  -> Reservation trigger observes consumed provenance
  -> stale/unavailable; no second durable mutation
```

The consumed Reservation reference is a deferred same-tenant FK because the handoff is marked consumed by a BEFORE INSERT trigger before the new Reservation row is physically visible as a referential target.

## 6. OfferingVersion freshness

Discovery candidate generation selects the latest OfferingVersion and requires that version to be bookable.

At Booking commitment, the handoff also fences current Offering identity/version. If a newer version became current after discovery, the old discovery option is stale rather than silently committing against historical catalog terms.

## 7. Provider privacy and accepted public profile

`provider_visibility=hidden` means concrete Resource identity must not cross the public F2 transport boundary.

Because `discoopt_v1` is an opaque random lookup token, hidden Resource identity is no longer recoverable by base64-decoding a signed payload.

The final F2 contract subsequently added an explicit minimal `ResourcePublicProfile`. A resource-specific Publication with `provider_visibility=public` may emit only its accepted public resource key/display name and optional role/profile-image reference. Private Resource fields, GlobalIdentity and SharedCapacityIdentity remain non-public.

A public provider Publication requires Resource scope and a usable active public profile. Visibility remains immutable for one Publication provenance row; changing visibility requires revoke + new publication.

## 8. Mapping provenance

Changing an Offering's canonical classification no longer mutates `service_classification_id` on the same mapping row.

Replacement is:

```text
lock Offering
revoke old mapping
insert new mapping
append audit linking superseded mapping
```

This preserves historical meaning and serializes two concurrent first-mapping attempts through the Offering lock.

Taxonomy lookup by tenant runtime is narrow function-based. `request_engine_app` no longer receives global SELECT enumeration over `service_classifications`.

Taxonomy retirement uses a separate narrow privileged predicate to determine whether any active cross-tenant mappings remain, avoiding FORCE-RLS blindness without exposing those mappings to the caller.

## 9. Publication scope hardening

One Publication row has immutable:

```text
Organization
Offering
Location
Resource/null scope
effective interval
provider visibility
```

Revocation is monotonic.

Broad (`resource_id IS NULL`) and resource-specific publications for the same Organization + Offering + Location cannot overlap in time. PostgreSQL serializes that mixed-scope rule with a transaction advisory lock plus overlap check so one appointment cannot be authorized simultaneously through ambiguous broad and specific provenance.

Resource-specific publications for different Resources may coexist.

## 10. Commercial eligibility

F2 search emits only F1-contextual appointment slots that contain deterministic:

```text
Location
configuration fingerprint
planned duration
amount
currency
```

Legacy tenant-local Booking remains supported by the existing public API. It is simply not eligible for F2 cross-tenant discovery until an equally explicit commercial/publication contract exists for that path.

## 11. Exhaustive ranking versus performance

Successful F2 responses preserve the contract ordering:

```text
1 earliest appointment start
2 distance_meters
3 stable Organization/Location/Offering/Resource/Publication tie-breakers
```

Current safe implementation uses a bounded exhaustive policy:

```text
eligible candidates <= 200
  -> evaluate every candidate
  -> globally sort resulting options

eligible candidates >= 201
  -> 422 discovery_search_too_broad
  -> caller narrows radius/window
```

A future batch availability adapter may improve performance but must remain behaviorally equivalent to the same ordering/authority contract.

## 12. SQL is defensive too

The protected cross-tenant search function independently validates canonical classification key, coordinates, radius, window ordering/span and internal result bound. HTTP validation is not considered sufficient protection for a SECURITY DEFINER surface.

The great-circle calculation clamps its intermediate expression to `[0, 1]` before `sqrt/asin`.

## 13. Error semantics

Search-contract failures are explicit 422 outcomes. A result set too broad to rank exhaustively is also 422 and never a silently partial success.

If Publication/Mapping changes between candidate evaluation and `discoopt_v1` issuance, that candidate is omitted. If it changes after issuance but before Booking, the commitment transaction returns ordinary opaque stale appointment semantics and writes no Reservation/CapacityClaim/outbox side effect.

## 14. Migration posture

The provisional F2 development steps are retained under `migrations/f2_steps/` as provenance. The production-facing history remains the single `0004_geospatial_cross_tenant_discovery` Alembic revision, which executes the accepted steps in order. Later corrections to the unreleased F2 consolidated contents remain governed by the pre-production evolution policy and must pass exact-head current-product bootstrap/evidence.

## 15. Closure evidence

The hardening requirements were incorporated into document 24 and the current guarantee/proof inventory. Exact-head CI after the final reconciliation must remain the authority for merge readiness; historical green runs do not prove a later head.
