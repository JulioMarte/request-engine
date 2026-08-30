# Request Engine V3 — Capability Registry

Status: normative for the current V3/post-V3 HTTP and security surface.

## Purpose

Capability keys are a machine-facing contract. They authorize a class of operation; they do not identify a Party and they never imply authority to act for a Party.

The authorization chain remains:

```text
authentication -> technical capability -> Party authority (when required) -> domain invariants
```

`src/request_engine/platform/security/capabilities.py` is the executable registry for the active product surface.

## Canonical naming

Capability keys describe the public operational vocabulary rather than persistence entities.

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
live_capacity.read
operational_recovery.read
operational_recovery.propose
operational_recovery.execute
operational_recovery.communicate
```

## Exposure classes

`public` means a capability may be granted to authenticated channels, applications, integrations, agents, or operators according to deployment policy. It does not mean anonymous access.

`operator` means the capability is reserved for privileged operational control or an explicit Party-authority override. Examples include `appointments.subject_override`, `queue.subject_override`, `requests.party_override`, `queue.call_next`, live-capacity configuration and F5 operational recovery.

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

F5 `operational_recovery.execute` is operator-only, but that technical grant does not itself grant authority over the Reservation subject. Execution delegates to Booking and therefore still requires ordinary `appointments.manage` subject authority or the explicit `appointments.subject_override` capability. F5 must not turn its operator capability into a hidden Party-authority bypass.

## F5 operational recovery

F5 registers three canonical operator capabilities and one internal automation authority:

```text
operational_recovery.read         query
operational_recovery.propose      idempotent command
operational_recovery.execute      idempotent command
operational_recovery.communicate  internal automation authority
```

`propose` is a command rather than a query because it persists an immutable proposal/provenance snapshot. It therefore requires `Idempotency-Key` under the normal command contract.

`operational_recovery.communicate` is not a public or operator HTTP capability. It names the authority under which the `operational_recovery_automation` service principal autonomously delivers customer-impact communication after a scheduled assessment commits a customer-impact outcome (contract 32 sections 13-14). It must never be granted to human channels.

`execute` authorizes one explicit proposal-bound recovery action. It does not imply a generic `reschedule all` workflow and it does not bypass Booking's authoritative Reservation/capacity validation.

## Legacy aliases

Existing tests/integrations may still materialize older grants. Compatibility remains one-way:

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

F5 introduces no legacy aliases.

## Change policy

Adding a capability requires a registry entry, exposure classification, a description, and Party-authority metadata when applicable.

Renaming or removing a canonical capability requires an explicit compatibility decision. Do not silently change capability strings in routers, SDKs, tool definitions, or agent manifests.

New HTTP capability checks must use canonical registry keys. Architecture fitness tests protect uniqueness, intentional alias fan-out, operator override classification and the command idempotency contract.

## Deferred discovery endpoint

The registry stabilizes authorization vocabulary, but it is not a tenant capability catalog. A future discovery endpoint must distinguish at least:

```text
capability exists in product
capability enabled for tenant
authenticated actor is granted capability
capability currently executable for a concrete Party/resource/context
```

Those are different facts and must not be collapsed into one boolean list.
