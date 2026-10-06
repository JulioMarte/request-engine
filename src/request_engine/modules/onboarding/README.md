# Onboarding

`onboarding` owns the cross-domain **readiness composition** used to answer whether an Organization has the minimum owner-backed facts required for supported setup journeys.

It owns:

- the `onboarding.read` readiness capability;
- the `/v1/onboarding/readiness` projection semantics;
- composition of readiness facts published by Tenancy, Catalog, Booking, Queue and Communications;
- readiness blockers derived from those facts.

The projection is advisory: each owner reader uses its own transaction, so the
report is not a global atomic snapshot and every suggested command revalidates
its own authority. The Tenancy reader additionally publishes tenant-scoped
identity/control facts (active and authenticatable controller, recorded-policy
readiness, staff-administration availability); when that reader fails its
section is reported as `unknown` (never ready) without fabricated blockers.
Recovery readiness is intentionally `unknown` in this iteration because
delivery/operator configuration is private-process readiness, not a tenant read.

Each configuration blocker points to a mounted owner operation where a safe next
step exists and supplies `resolution_hint`. This is preparation guidance, not
authorization or a promise that a single command fixes the journey. Creating a
resource still requires assignment/availability; configuration readiness proves
neither a bookable slot nor SMTP delivery. Business-Party readiness checks an
active organization-kind Party, not the tenant root/controller. Registration
does not provision a root or grant Representation authority. Missing controller
authentication requires operator investigation, not a replacement staff member.
Clients resolve operation IDs against the actual
OpenAPI schema and revalidate the owner's capabilities, revisions and inputs.

It does **not** own or mutate any source fact:

- Organization/Party/authority -> `tenancy`;
- Location/Offering configuration -> `catalog`;
- Resource/appointment supply -> `booking`;
- ServiceQueue state -> `queue`;
- communication-purpose configuration -> `communications`.

Current synchronous dependencies are therefore explicit and read-only:

```text
onboarding -> tenancy.contracts
onboarding -> catalog.contracts
onboarding -> booking.contracts
onboarding -> queue.contracts
onboarding -> communications.contracts
```

A readiness read must not provision missing state, infer authority, or mutate owner configuration. Owners publish the smallest facts needed; Onboarding decides only whether those facts satisfy the current setup/readiness projection.

This module exists because the capability is real and cross-domain. Do not move its aggregate policy back into `entrypoints`, `bootstrap` or an arbitrary owner merely to reduce visible fan-out.
