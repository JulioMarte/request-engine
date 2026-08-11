# 0003 — Module-first Python layout

**Status:** Accepted

## Context

A global `domain/`, `application/`, `infrastructure/`, `api/` layout scatters one business capability across the repository and makes ownership/navigation harder for humans and coding agents. Request Engine's business boundaries are already explicit and should be visible physically.

## Decision

Organize Python module first, layer second:

```text
src/request_engine/
  bootstrap/
  entrypoints/
  platform/
  modules/<business-module>/
```

Inside a business module, grow only the layers needed by real code. Preferred vocabulary is `domain`, `application`, `adapters`, `api`, and a deliberately small `contracts` public surface.

Cross-module imports use the target module's `contracts` surface only. `platform` must not depend on business modules. `bootstrap` is the composition root.

## Consequences

- Feature code, tests and ownership documentation are co-located by business capability.
- Database/provider implementations are adapters, not a generic global infrastructure layer.
- Architecture tests enforce dependency boundaries.
- Empty Clean Architecture scaffolding is discouraged.

## Rejected alternatives

- Global horizontal layer roots.
- One package/repository per database table.
- Premature microservice split.

Detailed normative rules live in `docs/09-python-module-architecture.md`.
