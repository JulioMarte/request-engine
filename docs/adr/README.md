# Architecture Decision Records

ADRs capture durable, hard-to-reverse architectural decisions. They explain **why** a constraint exists; canonical domain/transaction documents remain authoritative for detailed invariants and protocols.

Use an ADR when changing module boundaries, Python/PostgreSQL ownership, deployment/migration strategy, cross-module contracts, security/isolation posture, or another decision future maintainers are likely to question.

Format:

```text
# NNNN — Title
Status: Proposed | Accepted | Superseded

## Context
## Decision
## Consequences
## Rejected alternatives
```

Do not create ADRs for ordinary implementation choices that are easy to reverse.

Current records:

- `0001-modular-monolith.md`
- `0002-smart-postgresql-boundary.md`
- `0003-module-first-python-layout.md`
- `0004-agent-knowledge-system.md`
- `0005-capability-first-product-core.md`
- `0006-durable-transactional-communications.md`
- `0007-minimal-booking-capacity-model.md`
- `0008-tenant-rls-runtime-isolation.md`
- `0009-v3-database-contract-convergence.md`
- `0010-reservation-access-delivery-boundary.md` — proposed boundary to be accepted only after the ReservationAccess implementation and evidence prove it.
- `0011-cross-tenant-identity-and-shared-capacity.md` — proposed post-freeze direction; not part of the V3 baseline.
- `0012-contextual-resource-location-supply.md` — proposed post-V3 Resource-at-Location/contextual booking-supply extension; accept only after F1 implementation proves effective dating, stale-option behavior, historical commercial provenance and compatibility with existing/shared capacity.