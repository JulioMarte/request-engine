# Shared test fixtures

Use this directory only for test-world builders or immutable fixture data that are genuinely shared by multiple independent suites.

The normative authoring rules are in `docs/testing/evidence-authoring-guide.md` and `tests/AGENTS.md`.

Fixture principles:

- build minimal but complete valid business states;
- prefer descriptive scenario builders over bags of unrelated IDs;
- return typed identifiers/context needed by the test;
- use unique tenant/business keys when collisions could hide isolation defects;
- do not pre-create the outcome the operation under test is supposed to produce;
- do not disable constraints, triggers, RLS, authority checks, or transaction semantics to make setup easier;
- keep feature-specific builders beside their owning integration suite until more than one independent suite truly needs them;
- do not grow this directory into a global mega-fixture or a parallel domain model.

PostgreSQL proofs remain isolated by `tests/conftest.py`; shared fixture helpers must not introduce cross-test mutable state.