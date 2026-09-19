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
- `docs/testing/current-guarantees.toml` — normative machine-readable inventory of current semantic guarantees.
- `docs/testing/repository-governance-contract.md` — HARD / CONTROLLED / FLEXIBLE / HISTORICAL classification.
- `docs/testing/evidence-authoring-guide.md` — falsifiable proof workflow.
- `docs/architecture/docker-e2e-ci-plan.md` — **canonical reusable Docker platform for clean-install black-box system/E2E suites**.
- `docs/architecture/pre-production-evolution-policy.md` — KEEP / ADAPT / REPLACE / REMOVE / HISTORICAL policy.
- `docs/testing/current-proof-map.toml` — representative proof mapping.
- `docs/testing/test-architecture-migration.md` — test-taxonomy/disposition ledger.
- `tests/AGENTS.md` — executable working rules for test placement and authorship.

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

`.github/workflows/ci.yml` owns the general quality/current-product lanes. Specialized current-product PostgreSQL orchestration lives in `scripts/ci/run_current_product.sh`.

System/E2E installation and black-box execution is governed by `docs/architecture/docker-e2e-ci-plan.md` and the Docker E2E workflow/orchestrator that implements it.

These are different evidence classes:

```text
python-quality/current-product
    repository/module/DB guarantees

reusable Docker E2E platform
    clean install + external/system journeys
```

A green Docker E2E suite does not replace DB/architecture proofs, and a green in-process/current-product suite does not replace clean-install black-box evidence.

## Reusable system/E2E platform

The canonical direction for expensive cross-module journeys is:

```text
stable deployment definition
        ×
swappable suite
        ↓
fresh isolated world
        ↓
black-box evidence
```

The deployment is installed from scratch using the same Request Engine artifact for migrate/bootstrap/API/control-plane/worker plus separate PostgreSQL and optional providers.

The generic runner can select suites such as:

```text
smoke
booking
authority
recovery
worker
f01
oidc
all
```

The list is evolvable; it is not a frozen taxonomy. New ordinary suites should be registered declaratively rather than creating a duplicate Compose topology or copied GitHub workflow.

### Fresh-world default

Each system/E2E suite receives a clean authoritative world by default.

`all` means:

```text
reuse built images/caches
but
create -> migrate -> bootstrap -> run -> collect -> destroy
for each suite
```

It does **not** mean sharing a contaminated database between unrelated suites. Sharing a world requires an explicit justified grouping and proof that order dependence is not introduced.

### Black-box runner boundary

A normal system/E2E runner must not have:

- PostgreSQL route/DSN;
- `psycopg`/SQLAlchemy fixture authority;
- Request Engine repositories/services as shortcuts;
- Docker socket;
- host networking that bypasses the intended boundary.

If a system journey cannot be expressed through supported public/runtime contracts, that is usually a product/deployment gap, not permission to add SQL fixtures.

### Suite contract

A durable system/E2E suite declares at least:

```text
name and risk
selector
required services/profiles
fresh-world policy
fault-injection requirements
artifacts
PR/merge/nightly/manual eligibility
```

Suites may use different runner technologies only when the risk genuinely requires a different toolchain, such as load/browser testing. The same isolation principles still apply.

### Cost-aware execution

System/E2E is intentionally expensive. CI may select suites proportionally:

```text
PR                 -> smoke + risk-targeted suites
cross-cutting/merge -> conservative expanded set
nightly/manual      -> all / F-01 / recovery-fault / OIDC as appropriate
```

Path-based selection may optimize cost but cannot be the only protection for cross-cutting guarantees.

## Current python-quality lane

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

LOC/C901/file counts/fan-out remain review signals rather than universal hard merge cliffs unless a separate normative contract makes them HARD.

## PostgreSQL current-product proof

The authoritative PostgreSQL question for ordinary current development is:

```text
current source
+ exactly one current repository Alembic head
+ database upgraded to that head
        ↓
current accepted guarantees and product behavior
```

`scripts/ci/run_current_product.sh` owns that proof. It discovers the repository Alembic head rather than pinning an old feature revision, upgrades a clean PostgreSQL 18 database to it, verifies the revision, and runs current PostgreSQL/integration/E2E evidence appropriate to that lane.

Some surviving test paths still contain historical feature labels. Their names record origin, not architectural authority.

## Historical proof

Historical release evidence answers “what was proven then?”; it does not constrain current head to retain old schema/API/repository shape.

The former frozen-V3 lane has been retired from ordinary CI. V2 design-history checks, where still present, remain historical evidence rather than current-product semantic authority and require explicit later disposition.

Do not recreate historical lanes merely because old documentation references them.

## Test organization direction

The target is explicit coverage of critical risks with strong, localizable and falsifiable evidence, not a particular test count.

```text
tests/architecture      -> repository/architecture fitness
tests/modules           -> module-owned fast behavior/contracts
tests/db                -> PostgreSQL invariants/security/races
tests/integration       -> bounded component integration
tests/e2e or e2e suites -> reusable platform system journeys
```

The physical path of future reusable suites may evolve as the platform is implemented; the durable boundary is defined by `docker-e2e-ci-plan.md`, not by a frozen folder name.

A new architecture/test gate should answer:

1. **What risk does this assertion protect?**
2. **Is the asserted detail HARD/CONTROLLED, or merely FLEXIBLE implementation shape?**
3. **What plausible broken implementation makes this proof fail?**
4. **For system/E2E, could the runner cheat through DB/internals and still look green?**

If a legitimate feature can change an asserted filename/list/count without crossing a semantic boundary, prefer a semantic assertion. If no plausible relevant defect would make a behavioral test fail, redesign the test before treating it as evidence.
