# 0011 — Cross-tenant identity and shared capacity

Status: Accepted for development integration. This decision adds an optional shared-capacity serialization layer without replacing tenant ownership. Acceptance of the implementation remains subject to the pull request's exact-head CI/evidence gates; this ADR does **not** declare the global V3 freeze/release complete.

## Context

`Organization` remains Request Engine's security and administrative ownership boundary. `Party` and `Resource` are tenant-scoped, and baseline Booking uses tenant-local `Resource` as its capacity serialization root.

A real-world provider can nevertheless be independently bookable through multiple Organizations while representing one physical capacity: a doctor across clinics, a consultant across firms, a stylist across locations, or a technician shared by partners. Separate tenant Resources for that person can otherwise be booked concurrently.

Making `Resource` global would mix identity, tenancy, local policy and capacity ownership. Allowing tenants to inspect each other's Resources would break isolation. The accepted design therefore adds a hidden shared serialization root while preserving tenant-local aggregates.

## Decision

Keep identity, tenant representation and capacity serialization separate:

```text
GlobalIdentity
    opaque trusted control-plane identity for a real-world person/organization

Tenant Party
    tenant-local relationship/customer/provider representation

Tenant Resource
    tenant-local bookable capacity configuration

SharedCapacityIdentity
    optional hidden serialization root for one indivisible capacity

SharedCapacityBinding
    explicit trusted Resource -> SharedCapacityIdentity authorization

SharedCapacityClaimLink
    private CapacityClaim -> shared-root provenance
```

`SharedCapacityIdentity` is the persisted implementation name in this version. The design often calls it the “shared root” to emphasize its purpose. A future rename to `SharedCapacityRoot` would be nomenclature cleanup and is not required for correctness.

`CapacityClaim` remains the **sole authoritative capacity-consumption ledger**. Shared claim links contain serialization provenance only and do not duplicate interval, Reservation, Party, Offering or quantity truth.

The initial capability is restricted to `exclusive` Resources. Unit-sharing/CapacityPool semantics require a separate decision.

## Identity trust model

`GlobalIdentity` uses opaque internal UUID identity. Government IDs, email, phone and provider identifiers do not become public or primary identifiers, and this capability performs no heuristic automatic identity matching.

For a known `GlobalIdentity(kind='person')`, PostgreSQL permits only one active `SharedCapacityIdentity`, serialized by locking the GlobalIdentity during root creation. Organization identities may have multiple independent logical roots.

The database cannot determine that two distinct GlobalIdentity rows actually represent the same real person without a trusted external identity decision. Duplicate semantic identities can therefore fragment the mutex. Correct correlation, evidence and remediation are explicit control-plane responsibilities.

## Authorization and binding

Knowing a global/shared UUID does not grant authority.

Global identity creation, shared-root creation and binding activation/revocation occur only through audited `request_admin.*` functions. Private shared-capacity tables are not directly mutable through the supported control-plane role; direct DML privileges are revoked and `request_engine_app` / `request_engine_worker` cannot enumerate them.

Authority events preserve the caller-supplied `authority_ref` and reason while independently recording database session provenance and trusted request context when present. `authority_ref` is a business/control-plane reference, not authenticated actor identity.

Binding activation/revocation uses canonical `Resource -> shared root` locking. Activation backfills links for already-live local claims under those locks; revocation prevents new binding use while preserving historical claim links. Rebinding a Resource to another root is rejected while live provenance remains on the old root.

Global/shared identity retirement and merge/split are intentionally not supported operational workflows in this version even though schema statuses reserve retirement state.

## Booking serialization decision

For an operation that consumes/releases capacity:

```text
business root/children
    -> all affected tenant Resources, stable UUID order
    -> all active SharedCapacityIdentity roots, stable UUID order
    -> authoritative final validation/write
```

The protected runtime function validates tenant context/Resource ownership and itself enforces local-Resource-first locking before hidden roots.

Reschedule collects the union of old and new Resources before releasing the old commitment or creating replacements, preventing inverse old/new root acquisition.

For Queue/SlotOffer candidate selection, each speculative Resource combination executes in a nested transaction/savepoint. A losing combination rolls back its writes and locks before another candidate is tried, preserving the Queue-owned outer transaction.

## Database integrity decision

The implementation adds database-level defenses for the shared-capacity boundary:

- pre-RLS tenant guard before the privileged CapacityClaim capacity trigger;
- runtime-role classification that applies that guard to actual app runtime while excluding superuser/BYPASSRLS bootstrap/admin roles;
- opaque cross-tenant overlap rejection;
- append-only shared claim provenance;
- monotonic CapacityClaim release/replacement lifecycle;
- coherent Hold-to-Reservation claim promotion;
- one active shared root per known person GlobalIdentity;
- deterministic shared-root locking;
- SlotOffer creation locks and semantic source validation;
- deferred offered-state source consistency;
- accepted SlotOffer terminal consistency requiring consumed Hold, filled Opportunity, fulfilled Waitlist and complete coherent claim promotion to a confirmed Reservation;
- immutability of material Hold/Waitlist/Opportunity provenance once a SlotOffer references those rows, while preserving baseline mutation semantics before that historical boundary.

Unexpected `23P01` is normalized to ordinary unavailability only on operations that can acquire new capacity. It is not globally swallowed on release/confirm/accept paths where it could conceal corruption.

## Privacy decision

Cross-tenant conflict surfaces expose only the availability fact required to make a booking decision. They must not expose foreign Organization, Party/customer/patient, Reservation, Offering, shared-root, identity evidence or reason metadata.

App and worker roles cannot read private global/shared relations. Existing and nonexistent foreign CapacityClaim probes are rejected before privileged lookup with equivalent tenant-context semantics.

A legitimate caller can necessarily infer whether a shared physical capacity is busy/free for an interval by attempting availability/booking operations. Eliminating that fact is not a goal; preventing foreign identity/metadata disclosure is.

## Security boundary

RLS and tenant GUCs are defense-in-depth, not a promise that arbitrary SQL under a stolen full application DB credential is safe. Trusted Python transaction bootstrap, Principal/Representation authorization, least-privilege credentials and operational database timeouts remain required.

A compromised app credential can also create availability denial-of-service within the transactions/locks available to that credential. This is an operational containment problem, not a cross-tenant metadata-read capability granted by this ADR.

## Evidence and acceptance criteria

The implementation is covered by executable PostgreSQL/application evidence for:

- private-table least privilege and UUID-knowledge denial;
- runtime-role/pre-RLS oracle resistance;
- simultaneous cross-tenant Booking/Hold/SlotOffer contention;
- fallback across eligible Resources after hidden shared contention;
- reschedule rollback and inverse-root concurrency;
- binding activation/revocation/rebinding races;
- deterministic multi-root locking;
- CapacityClaim lifecycle/promotion/replacement provenance;
- person shared-root cardinality;
- SlotOffer creation, offered-state and accepted terminal consistency;
- historical SlotOffer source provenance;
- opaque public error behavior;
- PostgreSQL 18 bootstrap, catalog/schema equivalence and the repository's Phase 6 candidate evidence pipeline.

The normative extension invariants are `V3-I62..V3-I66`; concurrency aliases are `R25..R29` in the release matrices. Their global matrix state remains governed by the wider Phase 6 release process. Merging this feature does not imply that unrelated global V3 gates are complete.

## Consequences

Positive:

- prevents cross-Organization double booking for explicitly bound indivisible capacity;
- preserves tenant-local `Party`, `Resource`, policy and read authority;
- keeps `CapacityClaim` as one consumption truth;
- does not require public/global Resource exposure;
- supports provider/customer role differences across Organizations;
- produces auditable binding and serialization provenance.

Costs and residual assumptions:

- creates a trusted control-plane identity domain above individual Organizations;
- makes capacity lock topology and reschedule more complex for bound Resources;
- requires correct control-plane identity correlation to avoid duplicate real-person GlobalIdentity rows;
- exposes the legitimate busy/free availability fact of the shared capacity;
- does not yet implement identity merge/split/retirement operations;
- does not solve generalized shared unit capacity.

## Rejected alternatives

### Make `Resource` globally shared

Rejected. It conflates identity, tenant membership, local operational policy and capacity serialization and creates ambiguous RLS/authority semantics.

### Use government ID or contact data as primary identity

Rejected. These values are sensitive, mutable, jurisdiction-specific and unsuitable as public capability identifiers.

### Let Organizations query each other's Resources/Reservations

Rejected. Cross-tenant reads violate the isolation boundary and disclose operational/customer data.

### Rely only on manually partitioned schedules

Rejected as a correctness strategy. Manual schedules cannot serialize concurrent independent booking channels.

### Introduce a generalized CapacityPool now

Rejected. The demonstrated requirement is one indivisible real-world capacity shared by tenant-local Resources. Generalized unit pooling would materially enlarge the state model and concurrency contract without evidence that it is required here.

## Release boundary

This ADR accepts the architecture for integration into `development` once the exact PR head is green and mergeable. It does not supersede the global V3 Phase 6 construction/freeze gates, and it must not be cited as evidence that the overall V3 candidate is release-ready.
