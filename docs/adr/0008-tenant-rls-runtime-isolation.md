# 0008 — Tenant RLS and runtime database isolation
Status: Accepted

## Context

Composite tenant foreign keys prevent cross-tenant relational lineage but do not prevent a shared application database role from accidentally reading another tenant's rows. Request Engine will execute through HTTP agents, workers, provider callbacks and integration principals, so runtime blast-radius reduction matters before the first production baseline.

Per-tenant PostgreSQL roles/connections would provide stronger role-level isolation but create operational complexity disproportionate to the current multi-tenant product. Giving workers `BYPASSRLS` or schema-owner privileges would make ordinary worker bugs cross-tenant data bugs.

## Decision

V3 uses PostgreSQL Row Level Security as **defense-in-depth** for tenant-owned baseline tables, while preserving application-level Principal/Representation/domain authorization.

Conceptual runtime roles:

```text
schema_owner    NOLOGIN / migration ownership
request_app     normal API/application runtime, no BYPASSRLS
request_worker  worker runtime, no blanket BYPASSRLS
request_admin   explicit tightly controlled operations role
```

Production runtime never connects as schema owner or superuser.

Each tenant-scoped authoritative transaction sets a transaction-local Organization context after authentication/authorization resolution. RLS policies restrict tenant-owned rows to that Organization context.

Cross-tenant worker discovery is performed through narrow controlled claim primitives (for example `SECURITY DEFINER` functions for due outbox/ScheduledAction batches) rather than granting the worker unrestricted tenant-table visibility. The claim primitive returns the Organization needed for subsequent normal tenant-scoped execution.

Security-definer functions must:

- use a non-login owner;
- pin `search_path` to trusted schemas / `pg_catalog` as appropriate;
- expose only the minimum columns/actions required;
- be granted narrowly;
- be covered by privilege and object-shadowing tests.

RLS does not replace business authority checks. A shared runtime role that can set tenant context is still part of the trusted application computing base, so arbitrary SQL execution by compromised application code remains out of scope for RLS alone.

## Consequences

Positive:

- accidental missing tenant predicates fail closed for protected tables;
- worker bugs do not automatically gain broad tenant visibility;
- composite tenant FKs and RLS defend different failure classes;
- admin/worker cross-tenant capabilities become explicit audited surfaces.

Trade-offs:

- every DB transaction must establish correct tenant context;
- connection-pool hygiene and `SET LOCAL` semantics become correctness/security concerns;
- integration tests must exercise RLS/roles, not only schema constraints;
- security-definer functions require careful ownership/search-path discipline;
- this is defense-in-depth, not cryptographic tenant isolation against a fully compromised application runtime.

## Rejected alternatives

### Application WHERE clauses only

Rejected because one omitted predicate can expose cross-tenant data even when all FKs are structurally correct.

### `BYPASSRLS` for normal workers

Rejected because convenience would turn worker defects into cross-tenant data access.

### One PostgreSQL role per tenant

Deferred because it adds substantial connection/role lifecycle complexity and is not required for the first product baseline. It may be reconsidered for stronger isolation tiers later.
