# Architecture Decision Records

ADRs capture durable, hard-to-reverse architectural decisions. They explain **why** a constraint exists; canonical domain/transaction documents remain authoritative for detailed invariants and protocols.

Use an ADR when changing module boundaries, Python/PostgreSQL ownership, deployment/migration strategy, cross-module contracts, or another decision that future maintainers are likely to question.

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
