# Testing architecture

Request Engine testing separates **where a proof belongs** from **what risk it proves**, while also separating semantic rigidity from implementation flexibility.

The current repository operates under `docs/architecture/system-optimization-mode.md`. During this pre-production optimization phase, test filenames, release-era taxonomy and schema shape may evolve; semantic guarantees may not disappear silently.

Durable rules:

```text
physical location = ownership / execution boundary
pytest metadata   = evidence class / critical risk
HARD boundary     = fail closed unless an explicit stronger contract supersedes it
CONTROLLED shape  = drift alarm; deliberate evolution only
FLEXIBLE shape    = do not freeze incidental filenames/counts/private implementation
green test        = evidence only when it could fail for the claimed defect
```

Key references:

- `docs/architecture/system-optimization-mode.md` — current cohesion/rebaseline mode and change authority during this phase.
- `docs/testing/current-guarantees.toml` — normative machine-readable inventory of current semantic guarantees; it intentionally contains no exact test-file allowlist.
- `docs/testing/repository-governance-contract.md` — normative HARD / CONTROLLED / FLEXIBLE / HISTORICAL classification for repository architecture, DTO/type boundaries, naming, docs and LLM instructions.
- `docs/testing/evidence-authoring-guide.md` — normative workflow for falsifiable tests, realistic dummy data, PostgreSQL evidence, direct-SQL boundaries and false-positive avoidance.
- `docs/architecture/pre-production-evolution-policy.md` — KEEP / ADAPT / REPLACE / REMOVE / HISTORICAL disposition policy.
- `docs/testing/current-proof-map.toml` — non-normative migration/review map from guarantees to representative current proofs.
- `docs/testing/test-architecture-migration.md` — migration/disposition ledger for feature/release-era test restructuring.
- `tests/AGENTS.md` — executable working rules for test placement and authorship.
- `tests/fixtures/README.md` — conventions for reusable realistic test-world builders.

## Contributor / agent evidence flow

For every durable test change:

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

When PostgreSQL semantics are part of the claim, use real PostgreSQL 18 and the relevant runtime/application/database boundary. Direct SQL may establish valid preconditions or directly prove a database backstop, but it must not pre-create the expected outcome or bypass the authority, RLS, transaction, lock or constraint mechanism being claimed.

## Canonical CI ownership

`.github/workflows/ci.yml` owns runner/service orchestration. Reusable repository-local job content lives in `scripts/ci/ci_jobs.py` where a named reusable job exists; specialized PostgreSQL current-product orchestration lives in `scripts/ci/run_current_product.sh`.

The current `python-quality` job includes:

```text
non-blocking maintainability signal collection
environment / lock consistency
Ruff
Pyright
secret / Python security scans
dependency audit
architecture tests
unit tests
module tests
```

The historical script name `check_python_file_budget.py` does **not** mean a hard file-size budget remains active. It currently emits review evidence such as `QR-FSIZE-001`, `QR-CPLX-001`, navigation and coupling candidates. LOC/C901/fan-out are non-blocking review signals. `FILE_BUDGET_BASE_REF` is retained as an implementation/environment variable used to compare changed code against the integration base; it is not authority for a 120-line merge cliff or growth ratchet.

The workflow adds engineering-quality wrapper evidence around `python-quality`: baseline measurement, architecture diff, quality-policy separation, evidence finalization/schema validation, calibration summary and test-architecture inventory. Those wrappers provide provenance and review context; they do not redefine semantic product guarantees.

## PostgreSQL current-product proof

The authoritative PostgreSQL question for ordinary current development is:

```text
current source
+ exactly one current repository Alembic head
+ database upgraded to that head
        ↓
current accepted guarantees and product behavior
```

`scripts/ci/run_current_product.sh` owns that proof. It discovers the repository Alembic head rather than pinning an old feature revision, upgrades a clean PostgreSQL 18 database to it, verifies the database revision, and runs current PostgreSQL/integration/E2E evidence.

Some surviving test paths still contain `v3_*`, `f1_*`, `f2_*`, etc. Their names record origin, not architectural authority. They stay in current-product proof only when they still protect a current guarantee.

The semantic source of truth is `docs/testing/current-guarantees.toml`; shell path lists and the non-normative proof map are migration/selection mechanisms and may evolve as tests are consolidated.

## Historical V3 proof after unfreeze

The former active frozen-V3 compatibility lane has been retired from ordinary CI during `cohesion/system-optimization`:

```text
scripts/ci/run_v3_frozen_compatibility.sh   retired/removed
tests/historical/                           retired/removed from current tree
postgres-v3-bootstrap-proof                 retired from active workflow
postgres-v3-candidate-proof                 retired from active workflow
```

This does **not** mean the facts established by the V3 release never existed. V3 release documents, Git history/releases/tags and retained release artifacts remain provenance until the dedicated historical-archaeology phase dispositions them. Historical provenance answers “what was proven then?”; it does not constrain current head to keep the same schema/API/repository shape.

Do not recreate a frozen V3 lane merely because an old document references it. Reintroducing historical executable proof requires a concrete present-day provenance/compatibility need and an explicit governance decision.

## V2 history lane

`PostgreSQL 18 V2 design history` is still an active required check at the time of this optimization phase. It is **historical design evidence, not current-product semantic proof**. Its continued value, cost and required-check status are intentionally deferred to the release/historical archaeology disposition phase. Do not infer from its current presence that V2 schema/design shape is current product authority.

## Test organization direction

The target is not a particular test count. The target is explicit coverage of critical risks with strong, localizable and falsifiable evidence.

Current direction:

```text
tests/architecture  -> architecture/repository fitness functions
tests/modules       -> module-owned fast behavior/contracts
tests/db            -> cross-module PostgreSQL invariants/security/races
tests/e2e           -> production-like public/runtime journeys
tests/integration   -> integration scopes that remain useful while taxonomy is consolidated
```

Feature/release-era directory names are not constitutional. Before deleting, renaming or consolidating a durable proof, disposition the guarantee it protects through KEEP / ADAPT / REPLACE / REMOVE / HISTORICAL.

A new architecture test should answer:

1. **What risk does this assertion protect?**
2. **Is the asserted detail HARD/CONTROLLED, or merely FLEXIBLE implementation shape?**
3. **What plausible broken implementation makes this proof fail?**

If a legitimate feature can change an asserted filename/list/count without crossing a semantic boundary, prefer a semantic assertion. If no plausible relevant defect would make a behavioral test fail, redesign the test before treating it as evidence.
