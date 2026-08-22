# Testing architecture

Request Engine testing separates **where a proof belongs** from **what risk it proves**, while also separating **semantic rigidity** from **implementation flexibility**.

Durable rules:

```text
physical location = ownership / execution boundary
pytest metadata   = evidence class / critical risk
historical/       = pinned release provenance only
HARD boundary     = fail closed unless an explicit stronger contract supersedes it
CONTROLLED shape  = drift alarm; change only with an accepted architecture/product decision
FLEXIBLE shape    = do not freeze incidental filenames/counts/private implementation
green test        = evidence only when it could fail for the claimed defect
```

Key references:

- `docs/testing/repository-governance-contract.md` — normative HARD / CONTROLLED / FLEXIBLE / HISTORICAL classification for repository architecture, DTO/type boundaries, naming, docs and LLM instructions.
- `docs/testing/evidence-authoring-guide.md` — normative workflow for falsifiable tests, realistic dummy data, PostgreSQL evidence, direct-SQL boundaries and false-positive avoidance.
- `docs/architecture/pre-production-evolution-policy.md` — normative KEEP / ADAPT / REPLACE / REMOVE / HISTORICAL policy and current-vs-historical distinction.
- `docs/testing/current-guarantees.toml` — machine-readable inventory of current guarantees. It intentionally contains no exact test-file allowlist.
- `docs/testing/current-proof-map.toml` — non-normative mapping from guarantees to representative current proofs.
- `docs/testing/test-architecture-migration.md` — migration/disposition ledger for the V3/F1-to-current test restructuring.
- `tests/AGENTS.md` — executable working rules for placing and authoring tests.
- `tests/fixtures/README.md` — conventions for reusable realistic test-world builders.

## Contributor / agent evidence flow

For every durable test change, follow this order:

```text
identify guarantee/risk
        ↓
classify HARD / CONTROLLED / FLEXIBLE / HISTORICAL
        ↓
name a plausible defect that must make the test fail
        ↓
choose the real execution boundary needed to expose it
        ↓
build minimal but complete valid preconditions / dummy data
        ↓
exercise the real mechanism under test
        ↓
assert authoritative outcome + important absence of side effects
        ↓
run narrow proof
        ↓
run owning canonical CI lane
        ↓
require exact-head evidence before merge
```

Do not start from “what assertion can make this implementation look green?”. Start from the guarantee and the defect the proof must detect.

For database-dependent behavior, read `docs/testing/evidence-authoring-guide.md` before writing the fixture. PostgreSQL semantics are proved with real PostgreSQL, realistic isolated dummy data, and the relevant runtime/application/DB surface. Direct SQL may establish valid preconditions or prove a DB backstop, but it must not pre-create the expected outcome or bypass the authority/constraint/transaction mechanism being claimed.

## Canonical CI ownership

`.github/workflows/ci.yml` owns runner/service setup and passes execution context into the repository CI entry points. It should not independently redefine the content of a canonical test/quality job.

`scripts/ci/ci_jobs.py` is the executable source of truth for named reusable CI jobs such as `python-quality`. The current `python-quality` sequence owns the Python effective-line budget, environment/lock consistency, Ruff, Pyright, security/dependency checks, architecture tests, unit tests and module tests. The workflow passes `FILE_BUDGET_BASE_REF` so the file-budget ratchet can compare the current change with the correct integration base; local execution falls back to `HEAD^`.

Current-product PostgreSQL behavior is orchestrated by `scripts/ci/run_current_product.sh`; frozen release provenance remains in the historical compatibility lane. This separation prevents historical proof from freezing current implementation shape while keeping current guarantees continuously executable.

The target is not a particular number of tests. The target is explicit coverage of critical risks with strong, localizable, falsifiable evidence while keeping historical release provenance reproducible and unable to freeze current product evolution.

A new architecture test should answer two questions before it is accepted:

1. **What risk does this assertion protect?**
2. **Is the asserted detail HARD/CONTROLLED, or is it merely FLEXIBLE implementation shape?**

Every behavioral test should also answer a third:

3. **What plausible broken implementation makes this test fail?**

If a legitimate future feature could change the asserted filename/list/count without crossing a semantic boundary, prefer a semantic assertion instead of a snapshot. If no plausible relevant defect would make a behavioral test fail, redesign the test before treating it as evidence.
