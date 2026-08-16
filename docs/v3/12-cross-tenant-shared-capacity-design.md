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

The implemented mutation authority is the trusted Request Engine control plane represented at the database boundary by `request_engine_admin`. Ordinary `request_engine_app` and `request_engine_worker` sessions cannot create, discover or mutate global identity or binding state.

The privileged control-plane functions are:

- `request_admin.create_global_identity(...)`;
- `request_admin.create_shared_capacity_identity(...)`;
- `request_admin.activate_shared_capacity_binding(...)`;
- `request_admin.revoke_shared_capacity_binding(...)`.

Every creation, activation and revocation requires a non-empty `authority_ref` and reason and appends an immutable authority event. `authority_ref` is a caller-supplied control-plane/business reference; it is **not** treated as self-authenticating actor identity. Authority events are therefore stamped automatically with `session_user` plus request execution context when present (`authenticated_principal_id`, correlation id, principal kind and authentication method). The database session identity is independent of the caller-supplied label; request GUC values remain supplemental execution context.

The private global relations are SELECT-only to `request_engine_admin`. Direct INSERT/UPDATE/DELETE/TRUNCATE/REFERENCES/TRIGGER privileges are revoked so mutation cannot bypass the audited `request_admin.*` surfaces. App and worker roles have no direct table access to this state.

Knowing a `GlobalIdentity`, `SharedCapacityIdentity` or foreign `Resource` UUID conveys no binding authority.

Identity merge/split mistakes are intentionally **not** implemented as silent row rewrites. Until a dedicated merge/split protocol is designed and race-tested, remediation is: revoke incorrect bindings, preserve their audit history and create/authorize the corrected identity/root relationship. `GlobalIdentity` and `SharedCapacityIdentity` include a `retired` state in schema, but this branch does not expose a supported retirement command; retirement must not be advertised as implemented lifecycle functionality.

## Booking transaction model

The tenant-local Resource remains a capacity root. When a Resource has an active shared-capacity binding, Booking also serializes overlapping capacity commitments against the SharedCapacityIdentity.

The canonical lock topology is:

1. collect every tenant-local Resource that the operation may release or consume;
2. deduplicate and lock those Resource rows in UUID order;
3. resolve active bindings only through the protected runtime surface;
4. deduplicate and lock every corresponding `SharedCapacityIdentity` row in UUID order;
5. only after all roots are held, perform authoritative availability validation and mutate `CapacityClaim` state.

For reschedule, step 1 includes the union of old and new Resources before either old claims are released or new claims are created. For multiple mandatory requirements, all local Resources are locked before any shared root, and all roots use deterministic UUID ordering.

The runtime function `request_cmd.lock_shared_capacity_roots(organization_id, resource_ids)` returns no shared identifiers. The function itself enforces the lock protocol: it requires a non-null matching tenant context, validates that all supplied Resource ids belong to that tenant, locks those local Resource rows in UUID order, then locks the hidden shared roots in UUID order. Correctness therefore does not depend on a caller-only precondition that Resources were already locked.

`guard_capacity_claim()` remains the final capacity invariant and is `SECURITY DEFINER` solely because it must inspect private cross-tenant claim links. Because PostgreSQL evaluates row-level `WITH CHECK` policy after `BEFORE ROW` triggers, a separate tenant-context guard executes before this privileged trigger for app-role writes. Existing and nonexistent foreign identifiers therefore fail before privileged lookups with the same tenant-context rejection.

This does **not** turn the tenant GUC into a security boundary against a fully compromised `request_engine_app` database credential. The V3 database contract treats RLS as defense-in-depth; trusted Python execution binds tenant/actor context and Principal/Representation authorization remains authoritative. This feature must not be described as protecting against arbitrary SQL executed with a stolen application database credential.

## CapacityClaim lifecycle and provenance

Shared capacity makes historical `CapacityClaim` provenance security-relevant. The candidate therefore enforces:

- claims are created `active` and without a replacement edge;
- `released` claims cannot reactivate;
- a released Reservation claim may advance to `replaced` during legitimate reschedule;
- `replaced` is terminal;
- `released_at` and completed replacement provenance cannot be rewritten;
- a claim linked to shared capacity cannot change organization, Resource, requirement, Hold, interval, quantity or creation timestamp underneath its append-only link;
- a promoted Hold claim may acquire a Reservation id once, while active, but existing Reservation provenance cannot later be retargeted;
- when Hold and Reservation ids coexist on an active claim, both owners must describe the same subject, OfferingVersion, location and interval;
- `replaced_by_claim_id` must target a currently active claim for the same Organization, Reservation and requirement; self-replacement and replacement cycles are excluded by requiring the target to be active when the edge is recorded.

`CapacityClaim` remains the only capacity-consumption truth; these rules protect the historical explanation of that truth rather than introducing another ledger.

## SlotOffer transaction and integrity model

Queue owns the outer SlotOffer issuance transaction. Capacity selection can have multiple eligible Resource combinations. Each speculative combination therefore owns a nested transaction/savepoint containing its complete Resource/shared-root lock set, final revalidation and Hold/Claim writes. If a candidate combination loses capacity locally or through a hidden shared root, that savepoint rolls back its writes **and locks** before the next combination is attempted. The opportunity is closed for capacity loss only after every eligible combination fails.

The Queue-facing outer capacity adapter retains a savepoint so a PostgreSQL `23P01` cannot poison the Queue orchestration transaction. Non-capacity `IntegrityError` values are re-raised; only true capacity contention is translated to `SlotOfferCapacityUnavailable`.

`SlotOffer` itself links three independently valid tenant aggregates, so foreign keys alone are insufficient. While an offer is created in `offered` state, PostgreSQL locks semantic sources in the same order as Queue issuance:

1. `SlotOpportunity`;
2. `WaitlistEntry`;
3. `CapacityHold`.

It then proves that the opportunity is open, the waitlist entry is active, the Hold is live/unexpired, subject identity matches, Offering/OfferingVersion match, location constraints match, Hold interval equals the opportunity interval and the offer does not outlive either its Hold or the opportunity start. Those source locks remain through transaction completion, eliminating a status TOCTOU window.

After creation, `slot_opportunity_id`, `waitlist_entry_id`, `capacity_hold_id`, organization, expiry and creation timestamp are immutable. A lifecycle status change must advance revision, so raw SQL cannot transition an offer while preserving a stale optimistic-concurrency version.

## Capacity-conflict error boundary

Opaque capacity translation is deliberately narrow. `23P01` is translated to normal capacity-unavailable semantics only on operations that acquire potentially new capacity:

- direct Booking;
- CapacityHold acquisition;
- Reservation reschedule;
- SlotOffer Hold acquisition.

Cancellation, Hold confirmation, SlotOffer acceptance/promotion and capacity release operate on capacity already owned by the transaction protocol. A `23P01` there is not normal competition and is allowed to propagate as an invariant failure rather than being disguised as ordinary unavailability.

The public Booking API still returns the same opaque `appointment_unavailable` response for local and shared contention. The global HTTP integrity handler does not classify arbitrary PostgreSQL `23P01` errors as Booking failures.

## Privacy model

A tenant must never learn:

- the other Organization involved in a conflict;
- another tenant's Party/customer/patient;
- another tenant's Reservation identifier;
- appointment purpose or Offering;
- private schedule metadata;
- identity-linking evidence.

Cross-tenant conflicts collapse into the same public availability/unavailability semantics used for ordinary capacity contention. The normal app and worker roles have no table-level read grants on `global_identities`, `shared_capacity_identities`, `shared_capacity_bindings`, `shared_capacity_claim_links` or `shared_capacity_authority_events`.

The accepted availability contract necessarily allows a caller who is legitimately trying to book a shared physical capacity to learn whether a proposed interval is available. Repeated availability probes can therefore infer a busy/free pattern. This branch guarantees opacity of foreign identity, tenant, Reservation, Party, Offering and reason metadata; it does **not** claim to make the accepted busy/free availability fact unobservable.

## Required PostgreSQL properties

The implementation must prove:

- tenant-context guards prevent SECURITY DEFINER capacity checks from becoming a pre-RLS foreign-row oracle;
- shared-capacity serialization does not require cross-tenant table reads by ordinary tenant sessions;
- no ordinary tenant role can enumerate GlobalIdentity, SharedCapacityIdentity or bindings outside its authorized surface;
- admin cannot bypass control-plane mutation functions by direct private-table DML;
- binding activation/revocation is race-safe;
- booking cannot commit overlapping shared-capacity claims;
- reschedule is self-overlap safe and preserves valid replacement provenance;
- lock ordering is deterministic and deadlock resistant;
- SlotOffer source state is semantically coherent and serialized through offer creation;
- historical bindings and claim links remain auditable after revocation;
- shared-capacity state is included in bootstrap/equivalence evidence before this capability is accepted.

## Required evidence before acceptance

### Identity and authorization

- unauthorized Resource binding is rejected;
- knowledge of a global/shared UUID conveys no authority;
- cross-tenant identity correlation cannot be used as a read oracle;
- admin direct DML cannot bypass private authority mutation surfaces;
- authority events preserve caller reference and independently stamp database session provenance.

### Capacity races

- Org A vs Org B simultaneous booking for the same shared capacity: exactly one overlapping commitment may win;
- Hold vs Booking across Organizations;
- SlotOffer acquisition/acceptance vs direct Booking across Organizations, in both winner orders;
- SlotOffer retries a different eligible Resource after a hidden shared-root conflict;
- reschedule vs Booking across Organizations;
- simultaneous reschedules involving old/new shared roots;
- binding revocation vs new Booking;
- binding activation vs concurrent Booking;
- inverse multi-root acquisition does not deadlock;
- SlotOffer source-state locks prevent concurrent invalidation between validation and offer creation;
- retry/crash behavior preserves serialization and idempotency.

### Privacy

- conflict errors are tenant-indistinguishable from ordinary local unavailability at the public Booking boundary;
- nonexistent and foreign CapacityClaim probes are rejected before privileged lookup with equivalent tenant-context semantics;
- no foreign IDs or tenant metadata appear in HTTP responses, tenant-visible logs, audit projections or capability discovery;
- timing-sensitive tests must bound enumeration to the explicitly accepted busy/free availability fact.

### Backward compatibility

- unbound Resources retain current V3 transaction behavior;
- existing booking, waitlist, SlotOffer, lifecycle and ReservationAccess verticals remain green;
- legitimate reschedule continues to perform `active -> released -> replaced` claim history;
- no existing public capability requires a breaking request/response change merely to support shared capacity.

## Current evidence on this branch

Executable PostgreSQL/application tests have been added for:

- app/worker inability to enumerate private global state and admin SELECT-only private-table privileges;
- guessed foreign Resource UUID rejection through the protected root-lock surface;
- root-lock RPC self-enforcement of Resource-first ordering and fail-closed missing tenant context;
- pre-RLS oracle resistance for existing versus nonexistent foreign Resource probes;
- sequential/simultaneous cross-tenant capacity conflicts and half-open adjacency;
- Hold/Booking and SlotOffer/Booking winner orders;
- SlotOffer fallback to a second free Resource after first-choice hidden shared-root conflict without orphan Hold/Claim state;
- SlotOffer semantic source coherence, immutable provenance, revision advancement and source-row locking;
- Hold-to-Reservation subject/owner provenance;
- CapacityClaim non-reactivation and linked historical immutability;
- replacement-edge self-reference rejection and same-owner/requirement target constraints;
- control-plane authority event database-session/request-context stamping;
- cross-tenant reschedule rollback and inverse old/new root concurrency;
- binding activation/revocation races, backfill, historical-link preservation and unsafe different-root rebinding rejection;
- inverse multi-Resource/multi-root lock acquisition;
- opaque public Booking error mapping and narrow persistence-level capacity translation.

A prior feature head passed clean PostgreSQL 18 bootstrap, candidate equivalence, catalog audit, full V3 PostgreSQL/vertical tests, three repeated concurrency rounds, test-order independence, mutation probes and evidence validity. That evidence predates the latest security hardening migrations and **cannot** be used as final acceptance evidence. The current hardening head must repeat the complete candidate/evidence run successfully before ADR 0011 changes state.

## Documentation and fitness contract

This capability is architecture-sensitive. `docs/architecture/documentation-contracts.toml` protects every V3 candidate migration matching `*cross-tenant-*.sql`, dedicated `tests/db/test_v3_cross_tenant_*.py`, Booking persistence/error surfaces, production HTTP composition and the shared-capacity integration/privacy tests. Architecture tests explicitly prove that both the original shared-capacity migration and later provenance/SlotOffer hardening cannot change without this normative document changing in the same PR.

## Residual risks and explicit assumptions

- A fully compromised `request_engine_app` database credential is outside the protection supplied by RLS tenant GUCs; operational containment still requires least-privilege credentials, connection/statement/lock timeouts and normal SQL-injection prevention.
- A tenant may infer the accepted busy/free state of a genuinely shared physical capacity by attempting availability/booking operations; foreign metadata remains opaque.
- `request_cmd.lock_shared_capacity_roots()` has no arbitrary Resource-count cap because the current normative V3 contract permits `0..N` mandatory requirements and defines no maximum. A future cardinality limit must be introduced normatively, not invented by this migration.
- Global/shared identity retirement and identity merge/split remain intentionally unsupported operational workflows.
- Request-context GUC values recorded on authority events supplement `session_user`; they are not independently trusted against arbitrary SQL under a compromised database session.

## Delivery sequence

1. freeze identity/trust and binding authority semantics;
2. define schema, roles, RLS and protected control-plane surfaces;
3. define deterministic lock topology and booking transaction protocol;
4. implement DB invariants and adapters without changing public booking semantics;
5. integrate Booking/CapacityHold/SlotOffer/reschedule flows;
6. add adversarial cross-tenant concurrency, provenance and privacy tests;
7. keep documentation fitness and Phase 6 evidence inventory synchronized;
8. repeat the complete final CI/evidence run on the exact candidate head;
9. only after every required gate passes, promote ADR 0011 from Proposed to Accepted.

## Explicit non-goals for this branch

- making Resource global;
- exposing a global people directory;
- cross-tenant CRM/customer sharing;
- hiding the legitimate busy/free fact needed to make a booking decision;
- global schedule browsing;
- automatic identity matching based only on email/phone/government ID;
- defending arbitrary SQL executed with a stolen application database credential;
- changing unrelated V3 tenant-local booking semantics;
- declaring the final V3 freeze/release complete solely because this feature lands.
