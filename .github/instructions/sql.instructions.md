---
applyTo: "migrations/**/*.sql,migrations/**/*.py,src/**/persistence/**/*.py"
---

# PostgreSQL / persistence rules

- PostgreSQL 18+ is authoritative transactional storage.
- Critical tenant-owned relations preserve DB-provable tenant equality.
- Preserve stable serialization roots and canonical lock order.
- Do not replace typed foreign keys with generic entity type/id references.
- Do not turn `request_cmd` into a workflow backend; functions remain narrow consistency primitives participating in Python-owned transactions.
- `request_read` is a versioned query contract and never mutation authority.
- Historical outcome, financial, audit, and correction facts remain append-oriented.
- SQL changes must identify affected invariant IDs and include PostgreSQL-backed tests.
- Do not edit the pre-baseline design chain as if it were production history. See `migrations/README.md`.
