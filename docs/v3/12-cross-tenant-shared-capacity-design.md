# Cross-tenant identity and shared capacity — implementation design

Status: Active design branch. Not part of the accepted V3 baseline until the security, transaction, race, migration and evidence gates defined here pass.

## Goal

Allow one real-world capacity (for example a doctor, consultant, stylist or technician) to be represented by tenant-local Resources in multiple Organizations without allowing overlapping commitments and without exposing one tenant's reservation data to another tenant.

## Non-negotiable boundaries

- `Organization` remains the tenant security and administrative boundary.
- `Party` remains tenant-local and does not become a globally readable profile.
- `Resource` remains tenant-local and continues to carry Organization-specific booking configuration.
- Cross-tenant identity correlation never grants cross-tenant read authority.
- A shared-capacity conflict exposes only the minimum booking fact required by the caller, normally availability/unavailability.
- Government identifiers, email addresses, phone numbers and provider account IDs are not public or primary identifiers.
- Existing V3 tenant-local capacity behavior must remain unchanged for Resources that are not explicitly bound to shared capacity.

## Proposed concepts

### GlobalIdentity

Opaque internal identity for a real-world person or organization. It is not a public capability identifier and does not itself grant access to tenant data.

### SharedCapacityIdentity

Opaque serialization root representing one physical/logical capacity that may be referenced by Resources owned by different Organizations.

### SharedCapacityBinding

Explicit, auditable authorization linking a tenant-local Resource to a SharedCapacityIdentity.

Minimum conceptual state:

- `shared_capacity_identity_id`
- `organization_id`
- `resource_id`
- `status`
- `valid_from`
- optional `valid_until`
- authorization provenance
- immutable creation provenance
- revocation provenance

A binding must never be inferred merely from matching identity attributes.

## Booking transaction model

The tenant-local Resource remains a capacity root. When a Resource has an active shared-capacity binding, Booking must also serialize overlapping capacity commitments against the SharedCapacityIdentity.

Every operation that can change capacity must acquire all relevant lock roots in one deterministic global order before authoritative availability validation and mutation.

The design must cover:

- initial booking;
- CapacityHold acquisition/confirmation/release;
- SlotOffer promotion;
- cancellation;
- reschedule old/new Resource combinations;
- multiple mandatory Resource requirements;
- shared and non-shared Resources in the same request;
- binding activation/revocation racing with booking.

The canonical ordering must be deterministic across tenant-local Resource and shared-capacity roots so independent Organizations cannot deadlock each other through inconsistent lock order.

## Privacy model

A tenant must never learn:

- the other Organization involved in a conflict;
- another tenant's Party/customer/patient;
- another tenant's Reservation identifier;
- appointment purpose or Offering;
- private schedule metadata;
- identity-linking evidence.

Cross-tenant conflicts must collapse into the same public availability/unavailability semantics used for ordinary capacity contention.

## Binding authority

Creating or revoking a SharedCapacityBinding is privileged control-plane behavior. Normal tenant booking APIs cannot self-bind to a shared identity by presenting an identifier.

Before implementation is accepted, the branch must define the exact authority responsible for:

1. creating GlobalIdentity records;
2. verifying sensitive identity evidence when applicable;
3. creating SharedCapacityIdentity records;
4. approving Resource bindings;
5. revoking bindings;
6. resolving identity merge/split mistakes;
7. auditing every privileged transition.

## Required PostgreSQL properties

The implementation must prove:

- tenant RLS remains effective for Party, Resource and Reservation data;
- shared-capacity serialization does not require cross-tenant table reads by ordinary tenant sessions;
- no ordinary tenant role can enumerate GlobalIdentity, SharedCapacityIdentity or bindings outside its authorized surface;
- binding activation/revocation is race-safe;
- booking cannot commit overlapping shared-capacity claims;
- reschedule is self-overlap safe;
- lock ordering is deterministic and deadlock resistant;
- historical bindings remain auditable after revocation;
- shared-capacity state is included in bootstrap/equivalence evidence before this capability is accepted.

## Required evidence before acceptance

### Identity and authorization

- unauthorized Resource binding is rejected;
- knowledge of a global/shared UUID conveys no authority;
- cross-tenant identity correlation cannot be used as a read oracle;
- binding creation/revocation records trusted provenance.

### Capacity races

- Org A vs Org B simultaneous booking for the same shared capacity: exactly one overlapping commitment may win;
- hold vs booking across Organizations;
- SlotOffer acceptance vs direct booking across Organizations;
- reschedule vs booking across Organizations;
- simultaneous reschedules involving old/new shared roots;
- binding revocation vs new booking;
- binding activation vs concurrent booking;
- retry/crash behavior preserves serialization and idempotency.

### Privacy

- conflict errors are tenant-indistinguishable from ordinary local unavailability;
- no foreign IDs or tenant metadata appear in HTTP responses, logs intended for tenant consumption, audit projections or capability discovery;
- timing-sensitive tests should verify that nonexistent/foreign/shared conflicts do not create a practical enumeration surface beyond the accepted availability contract.

### Backward compatibility

- unbound Resources retain current V3 transaction behavior;
- existing booking, waitlist, SlotOffer, lifecycle and ReservationAccess verticals remain green;
- no existing public capability requires a breaking request/response change merely to support shared capacity.

## Documentation and fitness contract

This capability is architecture-sensitive. Any production change under the shared-capacity implementation surface must update this document or a more specific accepted successor document in the same PR.

The branch must add a documentation-contract registry rule before production implementation is considered complete. The gate itself requires positive and negative tests, following the existing worker-runtime documentation fitness pattern.

## Delivery sequence

1. freeze identity/trust and binding authority semantics;
2. define schema, roles, RLS and protected control-plane surfaces;
3. define deterministic lock topology and booking transaction protocol;
4. implement DB invariants and adapters without changing public booking semantics;
5. integrate Booking/CapacityHold/SlotOffer/reschedule flows;
6. add adversarial cross-tenant concurrency and privacy tests;
7. extend documentation fitness and Phase 6 evidence inventory;
8. only after all gates pass, promote ADR 0011 from Proposed to Accepted.

## Explicit non-goals for this branch

- making Resource global;
- exposing a global people directory;
- cross-tenant CRM/customer sharing;
- global schedule browsing;
- automatic identity matching based only on email/phone/government ID;
- changing unrelated V3 tenant-local booking semantics;
- declaring the final V3 freeze/release complete solely because this feature lands.
