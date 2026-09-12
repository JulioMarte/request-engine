# Onboarding

`onboarding` owns the cross-domain **readiness composition** used to answer whether an Organization has the minimum owner-backed facts required for supported setup journeys.

It owns:

- the `onboarding.read` readiness capability;
- the `/v1/onboarding/readiness` projection semantics;
- composition of readiness facts published by Tenancy, Catalog, Booking, Queue and Communications;
- readiness blockers derived from those facts.

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
