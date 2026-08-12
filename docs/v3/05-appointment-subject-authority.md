# V3 appointment subject authority

Status: normative convergence note for the appointment capability surface.

## Purpose

Tenant isolation and action permission are necessary but insufficient to authorize a Party-scoped appointment operation. A Principal that can invoke an appointment capability must still be authorized to act for the Reservation subject.

The connection surface is therefore:

```text
Authentication
    -> action capability
    -> subject authority
    -> authoritative booking transaction
    -> audit provenance
```

RLS proves tenant isolation. It does not prove same-tenant Party authority.

## Exact subject scopes

V3 uses exact scope keys; there is no wildcard or inheritance baseline.

```text
appointments.book    create a Reservation for the represented Party
appointments.manage  read, cancel or reschedule that Party's Reservation
```

A future capability that needs a different authority meaning must introduce a different exact scope rather than infer permission from participant roles, contact ownership or possession of an aggregate UUID.

## Operator path

Internal staff or service operators may be allowed to act across Party subjects without manufacturing a Representation. The authenticated actor must carry the separate operator permission:

```text
appointments.subject_override
```

This permission is distinct from action capabilities such as `booking.book_appointment`, `booking.read`, `booking.cancel_reservation` and `booking.reschedule_reservation`.

An action capability answers "may this Principal invoke this operation?". Subject override answers "may this Principal operate on a Party without delegated Representation?".

## Transaction rule

Mutation authority MUST be resolved inside the same tenant transaction that performs the authoritative write.

A flow such as:

```text
transaction A: Representation check -> COMMIT
transaction B: Reservation mutation -> COMMIT
```

is forbidden because revocation or expiry may occur between the two transactions.

For `book`, `cancel` and `reschedule`, the executor therefore checks either:

1. explicit operator override already materialized from the authenticated actor; or
2. a current exact-scope Representation using PostgreSQL wall clock.

The Representation path requires all of:

```text
same organization
same Principal
same represented Party
exact scope_key
Representation.status = active
Principal.active
Party.active
valid_from <= db_now
valid_until IS NULL OR valid_until > db_now
```

Idempotent replay of an already committed command may return the previously committed result without requiring authority to remain current because replay creates no new business effect.

## Read rule

Reservation status also requires subject authority. Possession of a Reservation UUID inside the same tenant is not sufficient.

Read authorization may use the published `tenancy.contracts.PartyAuthorityReader` because the read itself does not create a new authoritative mutation. Operator override remains explicit.

## Audit provenance

Every successful Party-scoped appointment mutation records the authority path used.

Representation path:

```json
{
  "mode": "representation",
  "scope_key": "appointments.book",
  "representation_id": "...",
  "authority_kind": "guardian|authorized_contact|self|delegated"
}
```

Operator path:

```json
{
  "mode": "operator",
  "scope_key": "appointments.manage",
  "representation_id": null,
  "authority_kind": null
}
```

This provenance belongs in AuditRecord, not in public outbox facts unless a future integration has a concrete need for it.

## Connection ownership

Booking may synchronously depend on `tenancy.contracts` for the stable authority vocabulary. Booking must not import Tenancy domain/application/adapter internals.

Concrete `PostgresPartyAuthorityReader` construction belongs to the process composition root, not the Booking router.

The approved module edge is therefore:

```text
booking -> tenancy.contracts
```

## Explicit non-goals

This change does not introduce:

- role hierarchy;
- wildcard scopes;
- policy DSL;
- authorization inferred from Party contact points;
- universal ACL tables;
- cross-tenant permission bypass;
- implicit staff authority from `principal_kind`.

CapacityHold acquisition/confirmation are not public HTTP appointment operations in this tranche. They must receive equivalent subject-authority policy before any future public exposure that can originate or convert Party-scoped capacity commitments.
