# Business module agent rules

Applies to `src/request_engine/modules/**`.

Before editing a module:

1. read `docs/10-module-ownership-map.md`;
2. read the module's `README.md`;
3. identify the authoritative command/query and affected invariant IDs;
4. inspect relevant PostgreSQL surfaces before changing persistence behavior.

Rules:

- Keep business behavior in the owning module.
- Do not import persistence/api/integration internals from another module.
- Cross-module references use public contracts/facades only.
- Do not add generic repository/service/helper abstractions to avoid deciding ownership.
- An authoritative command owns its transaction orchestration and follows documented lock order.
- Cross-module atomicity is allowed when required; do not replace it with async events for aesthetic separation.
- Provider SDK types stop at integration adapters.
- Domain code stays free of FastAPI and SQLAlchemy imports.
- Add code folders only when real code needs them; do not generate ceremonial empty clean-architecture trees.
