---
applyTo: "src/**/*.py,tests/**/*.py"
---

# Python implementation rules

- Python code is organized module first, layer second.
- Use Python 3.13 typing and keep public boundaries explicit.
- One authoritative command should have one obvious command file.
- Domain types, API/Pydantic schemas, and SQLAlchemy persistence mappings are distinct.
- Cross-module imports use only the target module's public contracts/facade.
- Prefer explicit dependencies over service locators or hidden globals.
- A SQLAlchemy `Session`/`AsyncSession` is transaction-scoped and must not be shared across concurrent tasks.
- Prefer explicit transaction framing for authoritative commands; do not rely on accidental implicit transaction starts.
- Use ORM for ordinary persistence and SQLAlchemy Core/explicit SQL for locks, ranges, `SKIP LOCKED`, aggregate concurrency checks, bulk workers, and `request_cmd.*` calls.
- No lazy-loading behavior may be required for correctness.
- Avoid `utils.py`, `helpers.py`, `common.py`, or `services.py` dumping grounds; put behavior with its owner.
