# Request Engine — Guardrail Decision Record

> **Status:** PROPOSED. This record preserves reasoning for the controversial quality-governance decisions in the Engineering Quality & Architecture proposal. It is not a replacement for feature/domain ADRs.
>
> **Audited state:** `development@a0eab9f48e91c900e2060a6bbef0812160910b6c`.

## Decision 1 — File LOC is not a HARD architecture invariant

### Context

Current enforcement uses effective code-bearing Python LOC with:

```text
target = 100
hard maximum = 120
```

At the audited state, new or previously compliant files above 120 failed the canonical Python quality job and legacy oversized files were ratcheted. The retirement decision (this record) demoted this to a non-blocking `QR-FSIZE-001` `REVIEW_CANDIDATE` signal; files above 120 no longer fail CI.

Current governance simultaneously says:

- file size is a maintainability/ownership fitness rule rather than a semantic HARD invariant;
- private internal file splits are FLEXIBLE;
- architecture fitness should protect intent rather than obsolete shape.

This creates an authority mismatch: a FLEXIBLE implementation detail can become merge-blocking solely because one proxy crosses a small numeric threshold.

### Decision

After proposal approval and migration, **file LOC SHALL be a REVIEW/trend signal, not a universal HARD architecture gate**.

No replacement universal hard threshold (`150`, `200`, `250`, etc.) is approved by this record.

Before any extreme-outlier hard zone is considered, the repository MUST publish and inspect distributions by code category and satisfy the HARD-gate proof obligation.

### Why

File LOC has useful signal but weak semantic precision.

It can identify overloaded files, but it cannot distinguish:

- large declarative vs large decision-heavy code;
- cohesive acceptance test vs mixed-responsibility implementation;
- one well-localized flow vs many small forwarding files.

The current hard target is easy to game mechanically. That is especially material because coding agents are explicitly part of Request Engine's development model.

### Alternatives rejected

#### Keep 120 HARD

Rejected because false-positive and gaming pressure are too high relative to the property actually protected.

#### Raise HARD to 200/250 immediately

Rejected because this preserves the same proxy-as-invariant model with a different arbitrary cliff. The current CI artifact does not publish sufficient repository distributions/outlier classifications to justify a new number.

#### Remove file-size measurement completely

Rejected because file size remains a cheap and useful outlier/review signal.

### Consequences

Positive:

- cohesive tests/declarative modules are not forced to fragment;
- coding agents lose a strong incentive for mechanical splitting;
- review can combine size with complexity/ownership/locality.

Negative:

- some genuinely overloaded files will no longer fail solely due to size;
- reviewers need a clear review signal and local-complexity data.

### Revisit trigger

A measured region of extreme file size consistently maps to maintainability problems with low legitimate exception rate and cannot be handled adequately by complexity/review signals.

---

## Decision 2 — Complexity is measured closer to the reasoning unit

### Context

Current Ruff configuration does not enable `C901` McCabe complexity. A small highly branching function can therefore satisfy the file budget while remaining difficult to understand.

Ruff provides a mature C901 implementation and documents default `max-complexity = 10` when enabled.

### Decision

Request Engine SHOULD introduce per-function McCabe complexity visibility using mature tooling, initially as **WARNING/reporting** rather than HARD.

`10` MAY be used as the first calibration warning because it is the Ruff default, but this record explicitly does **not** claim that 10 is the correct permanent Request Engine threshold.

No HARD complexity threshold is approved until:

- repository distribution is measured;
- outliers are manually classified;
- false positives are understood;
- helper-extraction/complexity-displacement gaming is tested;
- HARD proof obligation is satisfied.

### Why

Control-flow complexity is closer to the unit a developer reasons about than physical file size.

However, McCabe is still a metric. A declarative branch table can score high while remaining understandable, and complexity can be displaced across helpers.

### Alternatives rejected

#### Make C901 >10 HARD immediately

Rejected because tool default is convention, not repository evidence.

#### Use only function LOC

Rejected because length is still a proxy and can miss dense branching.

#### Introduce a custom composite “maintainability score”

Rejected as governance overengineering and hard to explain/game-test.

### Consequences

Complexity becomes visible without creating a new numeric refactoring treadmill.

### Revisit trigger

At least one representative development interval with distributions, manually classified warnings, and agent/human remediation observations.

---

## Decision 3 — Cohesion, locality, and navigability remain first-class human judgments

### Context

These properties matter materially but are not reliably derivable from file count, LOC, function count, or interface count.

### Decision

Cohesion by reason of change, locality of behavior, useful abstraction, and navigation cost SHALL remain **REVIEW-ENFORCED** properties supported by diagnostics rather than universal HARD thresholds.

The repository MAY report:

- tiny/forwarding-only files;
- delegation depth;
- files traversed;
- interface/implementation patterns;
- post-refactor file-count changes.

It MUST NOT turn those into opaque scores or universal limits without new evidence.

### Why

A one-function provider adapter may be an excellent boundary; a one-function forwarding wrapper may be useless. Static shape alone cannot reliably distinguish them.

### Consequences

Review guidance must be explicit enough that agents and humans understand that lower metrics do not override semantic regression.

---

## Decision 4 — Direct architecture boundaries remain HARD

### Context

Request Engine already has explicit, repository-specific boundaries:

- supported cross-module contracts;
- approved synchronous dependency directions;
- acyclic business graph;
- inward domain/application dependencies;
- dependency-light published contracts;
- technical-only platform;
- explicit composition boundaries.

### Decision

These properties SHALL remain HARD where detection is direct and precise.

The target HARD set is represented by:

```text
FF-DEP-001
FF-DEP-002
FF-DEP-003
FF-LAYER-001
FF-PLATFORM-001
FF-COMP-001
```

### Why

These checks measure architecture substantially closer to the protected property than LOC does. Their natural remediation usually improves or clarifies ownership.

### Anti-gaming requirement

Hard dependency rules MUST be paired with explicit prohibitions/review guidance against:

- re-exporting internals through contracts;
- moving business logic to platform/shared/common;
- duplicating business logic solely to avoid an edge;
- replacing required same-transaction consistency with asynchronous events merely to make a graph prettier.

### Evolution path

A new legitimate dependency follows:

```text
normative architecture decision
 -> policy update
 -> fitness update
 -> implementation/migration
 -> exact-head proof
```

Editing the allowlist first is not the evolution process.

---

## Decision 5 — Exact private repository shape is not automatically architecture

### Context

Some current architecture tests assert exact filenames, exact file presence, and exact source strings even when the underlying protected property is composition or transport ownership.

Examples include exact entrypoint filename allowlists and required `router.py`/`models.py` names.

### Decision

During migration, each exact-shape test MUST be traced back to its protected property.

- If the exact name/path is itself a supported public/tooling contract, retain it as CONTROLLED/HARD as justified.
- If the property can be detected semantically, replace the shape snapshot with semantic analysis.
- If the shape is a private implementation detail, downgrade/remove the HARD assertion.

### Why

Benign refactor stability is a required guardrail property. A file rename that preserves ownership/dependency direction should not require an architecture-policy ceremony unless the filename itself is intentionally public.

---

## Decision 6 — No universal policy for all code categories

### Context

Production domain code, orchestration, composition roots, schemas, migrations, and acceptance tests have different healthy shapes.

### Decision

Quantitative reports SHALL distinguish code categories before thresholds are calibrated.

At minimum:

```text
production source
tests
migrations/configuration
scripts
generated code
```

Generated code should normally be excluded from human-maintainability thresholds or reported separately.

Acceptance/integration/E2E tests MUST NOT be forced into production-style file-size limits merely for symmetry.

---

## Decision 7 — Exceptions are evidence about the rule

### Context

A weak guardrail often responds to false positives by accumulating suppressions, creating a bureaucracy that protects the metric instead of the architecture.

### Decision

Exceptions to HARD gates MUST remain explicit, rare, searchable, justified, and ideally owned/dated/expiring.

Heuristic REVIEW/WARNING signals SHOULD avoid per-instance suppression systems during calibration.

Repeated legitimate exceptions SHALL trigger a guardrail calibration review.

### Why

Exception growth can mean either unusual code or a bad rule. Governance must consider both hypotheses.

---

## Decision 8 — Legacy ratchets do not rescue weak proxies

### Context

The current file budget uses a ratchet for files already above 120: they may stay the same or shrink, but not grow.

### Decision

Ratchets remain an available migration mechanism only when the underlying measured property is sufficiently representative of the desired property.

A ratchet SHALL NOT be treated as inherently healthy simply because it prevents worsening by one metric.

When the file-size gate is migrated to REVIEW/trend, its old ratchet may remain temporarily for measurement continuity but SHALL NOT retain blocking authority solely because it already exists.

---

## Decision 9 — Custom blocking fitness functions require their own evidence

### Context

A custom checker capable of blocking all repository development is itself critical infrastructure.

### Decision

Custom HARD architecture checkers SHOULD expose fixture-testable logic with at least:

```text
positive fixture
negative fixture
boundary/alias fixture
failure-message behavior
```

Graph checks add cycle/new-module fixtures. Import checks add alias/relative import cases.

### Why

A brittle custom test should not become accidental architecture authority merely because it scans the live tree and happens to pass today.

---

## Decision 10 — Minimal sufficient governance wins over metric coverage

### Context

The exact-head CI already inventories 483 test files and 32 architecture-scope files. The repository does not have a governance scarcity problem.

### Decision

The quality migration SHALL prefer consolidation and stronger traceability over adding many new metrics.

The proposed maintainability set contains six semantic HARD functions, three warning/review diagnostics, and one informational trend function.

New gates require evidence of independent signal not already covered.

### Why

Every gate costs runtime, maintenance, developer attention, evolution friction, and false-positive handling. The guardrail system must remain simpler than the architecture it protects.

---

## Evidence references

Repository evidence:

- `docs/09-python-module-architecture.md`
- `docs/10-module-ownership-map.md`
- `docs/14-architecture-fitness-functions.md`
- `docs/testing/repository-governance-contract.md`
- `scripts/ci/check_python_file_budget.py`
- `tests/architecture/test_dependency_policy.py`
- `tests/architecture/test_repository_structure.py`
- `tests/architecture/test_connection_surfaces.py`
- `tests/architecture/test_repository_governance_contract.py`
- exact-head CI run `33572282764`

External calibration references:

- Ruff C901: <https://docs.astral.sh/ruff/rules/complex-structure/>
- Ruff settings: <https://docs.astral.sh/ruff/settings/#lint_mccabe_max-complexity>
- Linux kernel coding style: <https://www.kernel.org/doc/html/latest/process/coding-style.html#functions>
- Pylint `too-many-lines`: <https://pylint.readthedocs.io/en/latest/user_guide/messages/convention/too-many-lines.html>
- SonarSource Cognitive Complexity: <https://www.sonarsource.com/resources/cognitive-complexity/>
- Chowdhury, Uddin, Holmes: <https://arxiv.org/abs/2205.01842>

## Final decision

**YES, WITH EXPLICIT LIMITATIONS.**

The decisions above make it substantially more likely that a developer or coding agent following the guardrails improves the protected property instead of optimizing an arbitrary code shape. The limitations are explicit: quantitative distributions still need collection, cohesion/navigation remain partly human judgments, and current CI remains unchanged until this proposal is approved and migrated.
