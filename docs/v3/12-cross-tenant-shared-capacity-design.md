# Cross-tenant identity and shared capacity — implementation design

Status: Active design branch. Not part of the accepted V3 baseline until the security, transaction, race, migration and evidence gates defined here pass.

## Goal

Allow one real-world capacity (for example a doctor, consultant, stylist or technician) to be represented by tenant-local Resources in multiple Organizations without allowing overlapping commitments and without exposing one tenant's reservation data to another tenant.

## Non-negotiable boundaries

- `Organization` remains the tenant security and administrative boundary.
- `Party` remains tenant-local and does not become a globally readable profile.
- `Resource` remains tenant-local and continues to carry Organization-specific booking configuration.
- `CapacityClaim` remains the sole authoritative capacity-consumption ledger. Shared-capacity state serializes and validates claims; it does not create a second reservation ledger.
- Cross-tenant identity correlation never grants cross-tenant read authority.
- A shared-capacity conflict exposes only the minimum booking fact required by the caller, normally availability/unavailability.
- Government identifiers, email addresses, phone numbers and provider account IDs are not public or primary identifiers.
- Existing V3 tenant-local capacity behavior must remain unchanged for Resources that are not explicitly bound to shared capacity.

## Implemented concepts

### GlobalIdentity

Opaque internal identity for a real-world person or organization. It is not a public capability identifier and does not itself grant access to tenant data.

The V3 candidate stores no tenant-readable PII in this table. `evidence_ref`, when present, is an opaque control-plane reference to verification evidence rather than a public identity attribute.

### SharedCapacityIdentity

Opaque serialization root representing one physical/logical capacity that may be referenced by Resources owned by different Organizations.

### SharedCapacityBinding

Explicit, auditable authorization linking a tenant-local Resource to a SharedCapacityIdentity.

Implemented state includes:

- `shared_capacity_identity_id`;
- `organization_id`;
- `resource_id`;
- `status`;
- `valid_from`;
- optional `valid_until`;
- authorization provenance;
- immutable creation provenance;
- revocation provenance;
- monotonic revision.

A binding is never inferred merely from matching identity attributes. The first implementation accepts only `exclusive` Resources because `SharedCapacityIdentity` currently represents indivisible capacity: one physical/logical actor cannot satisfy two overlapping commitments.

### SharedCapacityClaimLink

Private serialization provenance connecting an authoritative `CapacityClaim` to the `SharedCapacityIdentity` it consumed when the claim was created or when a binding was activated around an already-live claim.

The link deliberately stores no interval, quantity, Reservation identifier visible to tenants, Party, Offering or Organization. It is not a second capacity ledger. The interval, lifecycle and quantity remain authoritative only on `CapacityClaim`.

Links survive binding revocation so revoking administrative authority cannot retroactively make an already-committed interval disappear from shared-capacity serialization. Rebinding a Resource to a different shared root is rejected while live claims still carry provenance for the previous root.

## Binding and identity authority

The implemented authority is the trusted Request Engine control plane represented at the database boundary by `request_engine_admin`. Ordinary `request_engine_app` and `request_engine_worker` sessions cannot create, discover or mutate global identity or binding state.

The privileged control-plane functions are:

- `request_admin.create_global_identity(...)`;
- `request_admin.create_shared_capacity_identity(...)`;
- `request_admin.activate_shared_capacity_binding(...)`;
- `request_admin.revoke_shared_capacity_binding(...)`.

Every creation, activation and revocation requires a non-empty trusted `authority_ref` and reason and appends an immutable authority event. Knowing a `GlobalIdentity`, `SharedCapacityIdentity` or foreign `Resource` UUID conveys no binding authority.

Identity merge/split mistakes are intentionally **not** implemented as silent row rewrites. Until a dedicated merge/split protocol is designed and race-tested, remediation is: revoke incorrect bindings, preserve their audit history and create/authorize the corrected identity/root relationship. Direct mutation that would rewrite historical claim provenance is forbidden.

## Booking transaction model

The tenant-local Resource remains a capacity root. When a Resource has an active shared-capacity binding, Booking also serializes overlapping capacity commitments against the SharedCapacityIdentity.

The canonical lock topology is:

1. collect every tenant-local Resource that the operation may release or consume;
2. deduplicate and lock those Resource rows in UUID order;
3. resolve active bindings only through the protected runtime surface;
4. deduplicate and lock every corresponding `SharedCapacityIdentity` row in UUID order;
5. only after all roots are held, perform authoritative availability validation and mutate `CapacityClaim` state.

For reschedule, step 1 includes the union of old and new Resources before either old claims are released or new claims are created. For multiple mandatory requirements, all local Resources are locked before any shared root, and all roots use deterministic UUID ordering.

The runtime function `request_cmd.lock_shared_capacity_roots(organization_id, resource_ids)` returns no shared identifiers. It verifies that every supplied Resource belongs to the current tenant context and then acquires the hidden shared-root locks.

`guard_capacity_claim()` remains the final database invariant. It is permitted to inspect private cross-tenant claim links under `SECURITY DEFINER`, but a cross-tenant overlap raises only the generic `capacity unavailable` conflict and never includes a foreign identifier or tenant detail.

The transaction model covers:

- initial booking;
- CapacityHold acquisition/confirmation/release;
- SlotOffer promotion through the existing CapacityHold path;
- cancellation;
- reschedule old/new Resource combinations;
- multiple mandatory Resource requirements;
- shared and non-shared Resources in the same request;
- binding activation/revocation racing with booking.

Queue owns the outer SlotOffer issuance transaction. Because a `23P01` raised by the shared-capacity guard aborts the current PostgreSQL transaction, speculative SlotOffer Hold acquisition runs inside a nested transaction/savepoint. A capacity loss rolls back only the speculative Hold/Claim writes, is translated to `SlotOfferCapacityUnavailable`, and allows Queue to close the `SlotOpportunity` in the still-valid outer transaction. The inverse proof asserts no orphan Hold, Claim or false active offer remains.

## Privacy model

A tenant must never learn:

- the other Organization involved in a conflict;
- another tenant's Party/customer/patient;
- another tenant's Reservation identifier;
- appointment purpose or Offering;
- private schedule metadata;
- identity-linking evidence.

Cross-tenant conflicts must collapse into the same public availability/unavailability semantics used for ordinary capacity contention. The normal app and worker roles have no table-level read grants on `global_identities`, `shared_capacity_identities`, `shared_capacity_bindings`, `shared_capacity_claim_links` or `shared_capacity_authority_events`.

Booking persistence translates the database `23P01` capacity invariant into the Booking-owned `AppointmentUnavailable` contract before the HTTP boundary. The Booking API then returns the same opaque `appointment_unavailable` response for local and shared contention. The global HTTP integrity handler intentionally does **not** classify every PostgreSQL `23P01` as a Booking error; doing so would incorrectly reinterpret unrelated future exclusion constraints.

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
- SlotOffer acquisition/acceptance vs direct booking across Organizations, in both winner orders;
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

## Current evidence on this branch

Executable PostgreSQL and application evidence now covers:

- ordinary tenant roles cannot enumerate global identities, shared roots, bindings, claim links or authority events;
- guessed foreign Resource UUIDs cannot be used as capabilities to reach hidden shared roots;
- sequential and simultaneous overlapping commitments across Organizations collapse to generic capacity unavailability, with exactly one winner in the concurrent case;
- half-open adjacent intervals remain independently bookable;
- Hold and direct Booking block one another across tenants;
- SlotOffer Hold first blocks a foreign Booking; the inverse foreign Booking first causes speculative SlotOffer capacity acquisition to roll back to its savepoint, closes the opportunity and leaves no orphan Hold/Claim/offer;
- SlotOffer acceptance promotes the existing linked claim rather than double-counting capacity;
- cross-tenant reschedule conflict rolls back and preserves the original Reservation, claim and shared-root provenance;
- simultaneous reschedules that touch inverse old/new shared roots synchronize before the real protected shared-root lock call and both complete under the canonical Resource-then-shared-root ordering;
- binding activation and revocation races serialize against claim creation, activation backfills a live claim, revocation preserves historical claim provenance, and unsafe different-root rebinding with a live link is rejected;
- inverse multi-Resource/multi-root acquisition commits without deadlock under the canonical deterministic ordering;
- Booking-owned public error mapping is opaque and does not expose the underlying database message;
- clean PostgreSQL 18 bootstrap, candidate equivalence, catalog audit, full V3 PostgreSQL/vertical suite, three repeated concurrency rounds, test-order independence, mutation probes and evidence validity pass on the pre-contract-update feature head.

The final acceptance run must be repeated after the canonical V3 invariant/race inventory is updated. ADR 0011 therefore remains `Proposed` until that final head is green.

## Documentation and fitness contract

This capability is architecture-sensitive. Any production change under the shared-capacity implementation surface must update this document or a more specific accepted successor document in the same PR.

`docs/architecture/documentation-contracts.toml` protects the shared-capacity migrations, Booking persistence/error boundary, production HTTP composition surfaces and all dedicated DB/integration/privacy tests. Positive and negative architecture tests prove that an unaccompanied protected change fails the documentation checker and the same change accompanied by this normative document passes.

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
