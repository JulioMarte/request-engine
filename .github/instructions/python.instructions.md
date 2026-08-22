---
applyTo: "src/**/*.py,tests/**/*.py"
---

# Python implementation rules

- Python is organized module first, layer second; follow `docs/09-python-module-architecture.md`.
- Use `docs/testing/repository-governance-contract.md` to distinguish HARD semantic/type boundaries from CONTROLLED architecture shape and FLEXIBLE private implementation.
- When changing tests, follow `docs/testing/evidence-authoring-guide.md`: a green test counts as evidence only when a plausible relevant defect would make it fail.
- PostgreSQL-dependent proofs use real PostgreSQL and minimal-but-complete realistic dummy data. Direct SQL may establish valid preconditions or prove DB backstops, but must not pre-create the expected outcome, disable enforcement, or bypass the runtime/transaction mechanism being claimed.
- Use Python 3.13 typing and keep public boundaries explicit.
- One authoritative command should have one obvious command file/use-case entry point.
- Domain types, application command/query types, cross-module contracts, API/Pydantic DTOs and SQLAlchemy persistence mappings are distinct.
- Pydantic business transport types stay at API/configuration boundaries; business-module `domain`, `application`, and `contracts` remain Pydantic-free.
- Top-level HTTP request DTOs use descriptive `*Body`; response/read projections use descriptive `*View`; transport-only query/path models use an explicit suffix such as `*Params`; nested request components may use a descriptive transport-explicit suffix such as `*InputModel`.
- Cross-module imports use only the target module's `contracts` surface, and those contracts use business language rather than transport/persistence suffixes.
- Application code defines ports; concrete DB/provider implementations live under the owning module's `adapters/`.
- Prefer explicit dependency injection from `bootstrap` over service locators or hidden globals.
- A SQLAlchemy `Session`/`AsyncSession` is transaction-scoped and must not be shared across concurrent tasks.
- Prefer explicit transaction framing for authoritative commands; do not rely on accidental implicit transaction starts.
- Use ORM for ordinary persistence and SQLAlchemy Core/explicit SQL for locks, ranges, `SKIP LOCKED`, aggregate concurrency checks, bulk workers and `request_cmd.*` calls.
- No lazy-loading behavior may be required for correctness.
- Avoid `utils.py`, `helpers.py`, `common.py`, `services.py`, `managers.py` or generic repository dumping grounds.
- Do not add abstract Unit-of-Work/repository hierarchies that merely wrap SQLAlchemy without a demonstrated domain/application need.
- Keep Python source/test files near 100 effective code lines. CI allows 101–120 effective lines without failure and blocks new/previously compliant files above 120. Blank lines and comment-only lines do not consume the budget; docstrings do. Existing >120-line debt may not grow. Do not waste tokens splitting a cohesive 102-line file merely to hit exactly 100.
