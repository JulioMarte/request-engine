# 0011 — Cross-tenant identity and shared capacity
Status: Proposed — preserved as pending post-freeze direction. This is a future feature the product wants to keep, but it is deliberately **not** part of the V3 baseline. It stays pending until a dedicated design phase resolves identity trust, shared-capacity serialization and cross-tenant isolation before any implementation is accepted.

## Context

Request Engine currently treats `Organization` as the security and administrative ownership boundary. `Party` and `Resource` are tenant-scoped. Booking uses `Resource` as the local capacity serialization root.

This is correct for the V3 baseline, but a common real-world case crosses that boundary: the same human professional can work for multiple independent organizations while representing one physical capacity.

Examples include:

- a doctor who works in two clinics and also runs a private office;
- a consultant who accepts bookings through multiple companies;
- a barber or stylist who works in several locations owned by different businesses;
- a technician who is independently bookable and also dispatched by partner companies.

The same human may also appear as a normal customer or patient in another Organization. Therefore, `Resource` cannot safely become the global identity of that person.

Without a cross-tenant capacity concept, two tenant-local Resources representing the same professional can be booked concurrently because each Organization sees a different serialization root.

## Proposed direction

Keep these concepts separate:

```text
GlobalIdentity
    who the real-world person or organization is

Tenant Party
    how one Organization knows or relates to that identity

Tenant Resource
    what that Organization is allowed to book

SharedCapacityIdentity
    optional physical/logical capacity shared by Resources across Organizations
```

Conceptually:

```text
                    GlobalIdentity
                         |
             +-----------+-----------+
             |                       |
         Org A Party               Org B Party
             |                       |
         Resource A                Resource B
             \                       /
              +-- SharedCapacityIdentity --+
```

`GlobalIdentity` must use an opaque internal identifier such as UUID. Government identifiers, email addresses, phone numbers or provider account IDs must not become public or primary identifiers. Sensitive identifiers require explicit verification, protected storage and controlled resolution.

A tenant-local `Party` may reference the same global identity without giving that tenant authority to inspect other tenants. Cross-tenant identity correlation must never imply cross-tenant data visibility.

A `Resource` remains tenant-scoped. It can carry Organization-specific availability, Offering eligibility, location, pricing context and booking policy without becoming a shared global aggregate.

A `SharedCapacityIdentity` is optional. Most Resources do not need one. When multiple tenant Resources are explicitly authorized to represent the same physical capacity, Booking may eventually serialize overlapping claims against that shared authority.

The only information another Organization should learn from a cross-tenant capacity conflict is the minimum fact required for booking, normally `available` or `unavailable`. It must not learn patient/customer identity, appointment purpose, source Organization or other reservation details.

## Authorization and binding

An Organization must not be able to bind an arbitrary Resource to a shared identity or shared capacity merely by knowing an identifier.

A future binding must have explicit authority and lifecycle, conceptually:

```text
SharedCapacityBinding
- shared_capacity_identity_id
- organization_id
- resource_id
- status
- valid_from
- valid_until?
- authorization provenance
```

Revocation of a binding must prevent new cross-tenant capacity commitments while preserving historical auditability.

## Booking implications

This proposal would materially change the current booking serialization model. Today, V3 uses tenant-local `Resource` as the capacity lock root.

If shared capacity becomes active, Booking must prove a deterministic lock protocol for combinations of:

```text
local Resource
optional SharedCapacityIdentity
old/new resources during reschedule
multiple mandatory resource requirements
```

The design must also prove:

- no double booking across Organizations sharing one capacity identity;
- no tenant data leakage through reads, conflicts, errors, telemetry or audit;
- no cross-tenant privilege escalation through identity correlation;
- deterministic deadlock-safe lock ordering;
- self-overlap-safe reschedule across local and shared roots;
- safe binding activation/revocation under concurrent booking;
- correct behavior when identity resolution is unavailable, if resolution is external;
- append-only provenance for sensitive identity linking decisions.

## V3 freeze decision

Do **not** make this part of the current V3 baseline or silently replace `Resource` as the serialization root during Phase 6.

The current V3 freeze must continue proving its accepted tenant-local booking model. This ADR exists so the product does not forget the real-world multi-organization professional case after freeze.

Promote this proposal into an implemented capability only after a dedicated design phase defines:

1. global identity ownership and trust model;
2. protected identifier verification and deduplication policy;
3. tenant Party ↔ global identity semantics;
4. shared capacity ownership and binding authority;
5. PostgreSQL schema and RLS posture;
6. lock ordering and transaction protocols;
7. invariant and race matrices;
8. public capability behavior that exposes no cross-tenant metadata;
9. migration/evolution path from the V3 local Resource serialization model.

## Consequences

Positive:

- preserves strong tenant isolation;
- supports professionals working across multiple independent businesses;
- prevents a global `Resource` aggregate from mixing identity, tenancy and capacity concerns;
- leaves room for cross-tenant double-booking prevention;
- allows one real person to be a provider in some Organizations and a customer/patient in others.

Costs:

- introduces a trust domain above individual Organizations;
- makes booking lock topology more complex when shared capacity is enabled;
- requires stronger privacy and authorization controls than ordinary tenant-local identity;
- creates lifecycle questions around identity merges, splits, verification and binding revocation.

## Rejected alternatives

### Make `Resource` globally shared

Rejected. It mixes real-world identity, tenant membership, operational configuration and capacity ownership. It also creates ambiguous authority and RLS semantics.

### Use government ID as the Resource/global primary key

Rejected. Government identifiers are sensitive PII, can change or be corrected, are jurisdiction-specific and must not become public capability identifiers.

### Let Organizations query each other's Resources to avoid conflicts

Rejected. This breaks the tenant security boundary and leaks operational data.

### Ignore the problem permanently and rely only on manual schedules

Rejected as a long-term product direction. Manual schedule partitioning can remain an initial workaround, but it does not prevent real double booking when one professional is independently bookable through multiple Organizations.
