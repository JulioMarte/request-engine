# Request Engine V3 — Capability Registry

Status: normative for the pre-baseline V3 HTTP/security surface.

## Purpose

Capability keys are a machine-facing contract. They authorize a class of operation; they do not identify a Party and they never imply authority to act for a Party.

The authorization chain remains:

```text
authentication -> technical capability -> Party authority (when required) -> domain invariants
```

`src/request_engine/platform/security/capabilities.py` is the executable registry for the active V3 surface.

## Canonical naming

Capability keys describe the public operational vocabulary rather than implementation modules or persistence entities.

Canonical examples:

```text
business.get_info
catalog.search_offerings
catalog.get_offering_details
appointments.find_slots
appointments.book
appointments.read
appointments.cancel
appointments.reschedule
queue.list
queue.join
queue.status
queue.leave
requests.submit
requests.read
requests.cancel
```

Implementation names such as `booking.book_appointment` are not canonical public vocabulary.

## Exposure classes

`public` means a capability may be granted to authenticated channels, applications, integrations, agents, or operators according to deployment policy. It does not mean anonymous access.

`operator` means the capability is reserved for privileged operational control or an explicit Party-authority override. Examples include `appointments.subject_override`, `queue.subject_override`, `requests.party_override`, and `queue.call_next`.

`internal` means the capability exists for trusted processing paths and should not be advertised as a normal customer/channel action. Request result/complete/fail processing is currently internal.

## Party authority metadata

A canonical capability may declare:

- `party_scope`: the exact Representation scope required when acting for a Party;
- `override_capability`: the explicit operator capability that permits an operator-controlled path instead of delegated Party authority.

Examples:

```text
appointments.book       -> appointments.book
appointments.read       -> appointments.manage
appointments.cancel     -> appointments.manage
appointments.reschedule -> appointments.manage
queue.join               -> queue.join
queue.status             -> queue.manage
queue.leave              -> queue.manage
requests.submit          -> requests.submit
requests.read            -> requests.manage
requests.cancel          -> requests.manage
```

The registry documents this relation; authoritative mutation handlers must still resolve current Representation state inside the transaction when the operation requires it.

## Legacy aliases

V3 is still pre-baseline, but existing tests/integrations already materialize older grants. Compatibility is therefore one-way:

```text
legacy grant -> may satisfy registered canonical requirement
canonical code -> must not require a legacy alias
```

Current migration aliases include:

```text
business.read                  -> business.get_info
catalog.read                   -> catalog.search_offerings + catalog.get_offering_details
booking.find_slots             -> appointments.find_slots
booking.book_appointment       -> appointments.book
booking.read                   -> appointments.read
booking.cancel_reservation     -> appointments.cancel
booking.reschedule_reservation -> appointments.reschedule
booking.subject_override       -> appointments.subject_override
queue.read                     -> queue.list + queue.status
```

The two legacy read umbrellas intentionally fan out only for compatibility. New grants should use the narrower canonical keys.

Aliases are not advertised as new capability vocabulary and should be removed at the V3 compatibility freeze once deployment adapters have migrated.

## Change policy

Adding a capability requires a registry entry, exposure classification, a description, and Party-authority metadata when applicable.

Renaming or removing a canonical capability requires an explicit compatibility decision. Do not silently change capability strings in routers, SDKs, tool definitions, or agent manifests.

New HTTP capability checks must use canonical registry keys. Architecture fitness tests protect uniqueness, intentional alias fan-out, and operator override classification.

## Deferred discovery endpoint

The registry stabilizes authorization vocabulary, but it is not yet a tenant capability catalog. A future discovery endpoint must distinguish at least:

```text
capability exists in product
capability enabled for tenant
authenticated actor is granted capability
capability currently executable for a concrete Party/resource/context
```

Those are different facts and must not be collapsed into one boolean list.
