# Request Engine — Repository Engineering Quality & Architecture Guardrail Audit

> **Status:** PROPOSED audit and policy basis. This document records evidence and recommendations; it does not itself modify current enforcement.
>
> **Repository:** `JulioMarte/request-engine`
>
> **Authoritative audited state:** `development@a0eab9f48e91c900e2060a6bbef0812160910b6c`
>
> **Exact-head CI evidence:** GitHub Actions CI run `33572282764` / run `#3253`, conclusion `success`.
>
> **Method:** inspect current canonical documentation, module ownership, source layout, architecture tests, CI orchestration, file-budget implementation, representative source/commit outliers, and external tooling/research. No production code, architecture tests, linter configuration, or CI enforcement was changed during this phase.

## 1. Executive verdict

Request Engine already has a stronger architectural governance foundation than most repositories of comparable size. Its best rules protect real semantics: module ownership, contract-only cross-module imports, explicit dependency direction, acyclic dependencies, inward layer boundaries, platform purity, and explicit composition surfaces.

The main maintainability weakness is not lack of governance. It is **misallocated authority inside the governance system**.

The current repository says in prose that internal file splits are FLEXIBLE and that architecture tests should protect semantic boundaries rather than obsolete shape, yet the Python quality job blocks new/previously compliant Python files above **120 effective code lines**. The same 100/120 target is repeated in coding-agent instructions. This converts a coarse size proxy into a target that both humans and agents are strongly incentivized to optimize.

That is not well aligned with the repository's own stated goals of cohesive capability-local code and minimal ceremony.

At the same time, current Ruff configuration does **not** enable function-level McCabe complexity (`C901`). Therefore the enforcement system can reject a cohesive 121-line file while allowing a much smaller but genuinely difficult branching function, provided other lint/type rules pass.

The proposed correction is not “remove limits and trust taste.” It is:

1. keep direct architectural invariants HARD;
2. add function-level complexity as a calibrated warning/review signal;
3. demote file LOC from a universal blocking target to review/trend authority;
4. add lightweight navigability/fragmentation review pressure so complexity cannot simply be displaced into wrappers;
5. consolidate duplicate/static-shape architecture assertions around the semantic property they actually protect;
6. measure the repository before hardening any new quantitative threshold.

**Verdict on current guardrail alignment:** **NO, not fully aligned yet.** The architecture-boundary system is strong, but the 100/120 file target has more blocking authority than its signal quality justifies.

**Verdict on the proposed contract:** **YES, WITH EXPLICIT LIMITATIONS.** It should produce healthier default incentives if the migration preserves semantic HARD gates and does not replace the 120 rule with another uncalibrated number.

Evidence confidence:

- architectural boundary findings: **HIGH**;
- 100/120 incentive mismatch: **HIGH** as a policy/incentive finding;
- claim that a particular current micro-file exists specifically because of the cap: **MEDIUM/LOW** unless commit history states that motive;
- recommended navigability diagnostics: **MEDIUM** engineering judgment;
- any exact future complexity/file-size HARD threshold: **LOW until measured**, therefore none is proposed.

## 2. Documented vs Observed vs Enforced architecture

### 2.1 Documented architecture

The strongest current documentation describes a modular monolith organized **module first, layer second**.

Current ownership is explicit across:

```text
tenancy
catalog
requests
booking
queue
communications
discovery
delivery
live_capacity
operational_recovery
operational_copilot
payments (deferred)
dispatch (deferred)
```

`platform` is technical infrastructure, not business ownership. `bootstrap` and entrypoints are composition/process boundaries. Cross-module use is expected through published contracts.

The current ownership map is materially stronger and more current than some older transition text. For example, `docs/10-module-ownership-map.md` treats `delivery` as active post-V3 F3, while `docs/09-python-module-architecture.md` still contains transition-era language that describes `delivery` as deferred/incubating. `docs/README.md` explicitly points F3 readers to the current Queue/Delivery ownership map, so the ownership map/post-V3 contracts should prevail.

This is a documentation-drift finding, not evidence that the architecture itself is wrong.

The governance contract also classifies:

- HARD semantic boundaries;
- CONTROLLED architecture/product shape;
- FLEXIBLE private implementation shape;
- HISTORICAL pinned provenance.

Importantly, that same document explicitly lists **internal file splits** as FLEXIBLE.

### 2.2 Observed architecture

Observed source layout matches the modular-monolith thesis:

```text
src/request_engine/
  bootstrap/
  entrypoints/
  platform/
  modules/
```

The business module set includes post-V3 modules such as `live_capacity`, `operational_recovery`, and `operational_copilot` in addition to the baseline modules.

The observed `operational_copilot` module is a useful maintainability hotspot because its purpose necessarily spans many owner contracts. Its approved dependency policy permits dependencies on seven business modules:

```text
booking
catalog
discovery
live_capacity
operational_recovery
queue
tenancy
```

This fan-out is not automatically a design defect: F6 is explicitly an agent-facing composition/admission boundary. It does, however, make navigability and wrapper proliferation more material in that module than in a simple owner module.

Representative observed micro-files include:

- `operational_copilot/api/recovery.py`, which primarily constructs/returns one adapter behind one function;
- `operational_copilot/adapters/resolution_common.py`, a tiny shared `require_one()` helper;
- multiple paired `tool_*_models.py` / `tool_*_router.py` files and narrow executor/resolution adapters.

These files are **not declared violations**. Some are legitimate boundary adapters. Their existence is evidence that “small file” is not itself enough to prove useful modularity and that a repository-wide hard size target must be evaluated against navigation cost.

### 2.3 Enforced architecture

Enforcement is broad and generally serious.

Current Python quality executes:

```text
Python effective line budget
uv/environment resolution
lockfile consistency
Ruff lint
Ruff format
Pyright strict
secret scan
security static analysis
vulnerability audit
architecture tests
unit tests
module unit tests
```

Architecture tests enforce, among other things:

- contracts-only cross-module imports;
- approved synchronous module edges;
- acyclic module graph;
- domain/application layer restrictions;
- public contract dependency restrictions;
- platform isolation;
- entrypoint/module composition boundaries;
- DTO/type separation;
- selected repository/doc/instruction shape;
- serialized branch integration workflow.

The key documented/enforced mismatch is the file budget:

- governance calls file size a maintainability/ownership fitness rule, **not a semantic HARD invariant**;
- internal file splits are documented as FLEXIBLE;
- CI nevertheless makes `>120` a blocking outcome for new/previously compliant `src` and `tests` files;
- agent instructions repeat the same numeric target.

That is exactly the kind of authority inversion this audit is intended to correct.

### 2.4 Material architecture drift findings

| Finding | Documented | Observed/enforced | Severity |
|---|---|---|---|
| File split is FLEXIBLE | governance contract says yes | hard 120 cap can force split to merge | HIGH governance mismatch |
| File size not semantic HARD | governance says yes | effective behavior is HARD CI failure | HIGH governance mismatch |
| Delivery current status | current ownership/F3 docs: active | repository-structure test still labels `delivery` in `DEFERRED_MODULES` | MEDIUM stale policy naming/shape |
| Semantic fitness over snapshots | architecture docs say protect intent | some tests assert exact filenames/source strings | MEDIUM benign-refactor fragility |
| Local complexity | architecture values comprehensibility | Ruff C901 not enabled | HIGH missing signal relative to file LOC authority |

## 3. Repository Engineering Risk Model

Severity describes engineering impact if the risk materializes; exposure reflects current controls.

| Risk | Severity | Current exposure | Concrete evidence / reason |
|---|---|---|---|
| Cross-module implementation coupling | CRITICAL | LOW-MEDIUM | strong contracts-only AST checks exist |
| Ownership/dependency-direction erosion | CRITICAL | LOW-MEDIUM | explicit dependency policy + cycle detection exist |
| Framework/persistence/transport leakage inward | HIGH | LOW-MEDIUM | multiple layer/type checks exist |
| Dependency cycles | HIGH | LOW | direct graph detector exists |
| Shared/platform dumping ground | HIGH | MEDIUM | direct imports/names blocked; semantic policy placement still human-judged |
| Small-but-complex functions | HIGH | MEDIUM-HIGH | no C901; file LOC can be low while branching is high |
| Artificial fragmentation / navigation explosion | HIGH | MEDIUM-HIGH | universal 120 blocking target + many small adapter/support files |
| Complexity displacement into helpers | HIGH | MEDIUM | no aggregate semantic check; helper extraction can lower local scores |
| Test fragmentation | HIGH | MEDIUM-HIGH | same 120 blocking policy applies to tests |
| Exact-shape architecture ossification | MEDIUM | MEDIUM | filename allowlists, exact `router.py/models.py`, source-string assertions exist |
| Excessive public contract surface | MEDIUM | MEDIUM | contracts are constrained, but growth/fan-out is not trend-reported |
| Generic abstraction/interface proliferation | MEDIUM | MEDIUM | prose warns against ceremony; hard detection would be unreliable |
| Duplicate architecture-policy implementations | MEDIUM | MEDIUM | overlapping domain/contracts/cross-module checks appear in several files |
| Suppression/exception growth | MEDIUM | LOW today | limited explicit suppression system; future heuristic gates could create it |
| Architecture governance overengineering | MEDIUM | MEDIUM | already 32 architecture-scope test files; new rules should be minimal |
| Line length/format style | LOW | LOW | mature Ruff tooling; not an architecture risk |

## 4. Existing Gate Inventory

### 4.1 Generic mature tooling worth preserving

| Mechanism | Role | Classification | Disposition |
|---|---|---|---|
| Ruff lint `E,F,I,UP,B,ASYNC,SIM` | correctness/style/static smells | HIGH-SIGNAL generic tooling | PRESERVE |
| Ruff format | deterministic formatting | direct style conformance | PRESERVE |
| Pyright strict | type consistency | HIGH-SIGNAL | PRESERVE |
| secret scan | credential leakage | security invariant/signal | PRESERVE |
| Bandit/static security | security smells | HIGH-SIGNAL | PRESERVE |
| dependency audit | known vulnerable deps | security supply-chain signal | PRESERVE |

### 4.2 Architecture-specific enforcement

| Mechanism | Protected intent | Classification | Disposition |
|---|---|---|---|
| contracts-only module import rule | module encapsulation | DIRECT INVARIANT | PRESERVE HARD |
| approved module dependency policy | ownership direction | DIRECT INVARIANT | PRESERVE HARD |
| cycle detection | acyclic ownership topology | DIRECT INVARIANT | PRESERVE HARD |
| domain outer-layer restrictions | framework independence | DIRECT INVARIANT | PRESERVE HARD |
| application adapter/transport restrictions | ports/adapters direction | DIRECT INVARIANT | PRESERVE HARD |
| contract dependency restrictions | stable public surfaces | DIRECT INVARIANT | PRESERVE HARD |
| platform cannot import business modules | technical platform purity | DIRECT INVARIANT | PRESERVE HARD |
| entrypoints do not import module adapters | composition boundary | DIRECT INVARIANT | PRESERVE HARD |
| generic business filename bans | ownership clarity | HIGH-SIGNAL STRUCTURAL RULE | KEEP NARROW; do not confuse name with semantics |
| exact entrypoint filename allowlist | process shape | CONTROLLED/weak proxy | REWRITE/DOWNGRADE |
| exact `router.py`/`models.py` presence | private layout | INVALID PROXY for HARD architecture | REMOVE from HARD role unless a public tool requires it |
| exact installer source strings | connection convention | weak mechanism for good intent | REPLACE semantically |
| branch lane topology | integration serialization | DIRECT PROCESS INVARIANT | PRESERVE, but treat separately from code maintainability |

### 4.3 File budget

Current `scripts/ci/check_python_file_budget.py` implements effective code-bearing physical LOC and uses:

```text
target: 100
hard maximum: 120
```

Its intended remediation message is better than a raw threshold because it says not to minify/truncate. However, the blocking condition still creates a simple target: get the changed file at or below the number.

Classification:

```text
file LOC as a signal           -> HEURISTIC
universal 120 as HARD target   -> HARMFUL INCENTIVE / INVALID PROXY for HARD
legacy ratchet on same proxy   -> HEURISTIC ratchet, not strengthened by being a ratchet
```

## 5. Risk -> Property -> Signal -> Enforcement Matrix

| Risk | Desired property | Best current/proposed signal | Enforcement |
|---|---|---|---|
| cross-module internals | consume only published owner surfaces | forbidden import edge | HARD |
| unreviewed dependency direction | topology is explicit | edge absent from approved graph | HARD |
| cycles | acyclic ownership | graph cycle | HARD |
| framework leakage | semantic layers stay framework-independent | forbidden origin/import | HARD |
| platform dumping ground | technical shared layer stays business-neutral | platform->module edge + semantic review | HARD + REVIEW |
| complex local reasoning | functions remain understandable | McCabe + nesting/branches/outlier review | WARNING/REVIEW initially |
| overloaded file | cohesive responsibility | file LOC plus conceptual review | REVIEW |
| fragmentation | reasoning path stays local | tiny/forwarding files + delegation/path review | REVIEW |
| test fragmentation | scenario world remains local | support hops/file split review | REVIEW |
| public contract creep | contracts stay narrow/stable | dependency/fan-out/surface trend | HARD for leakage; INFORMATIONAL for size |
| policy duplication | one obvious fitness owner | duplicate checker inventory | REVIEW |
| suppression growth | rules remain calibrated | exception/suppression trend | INFORMATIONAL -> review trigger |

## 6. Gates worth preserving

The strongest current architecture checks should survive largely unchanged in intent:

1. **Cross-module imports through supported contracts only.** This directly protects encapsulation and independent evolvability.
2. **Explicit synchronous dependency directions.** The current policy table makes architectural change reviewable instead of accidental.
3. **No dependency cycles.** Detection is precise and remediation starts with ownership rather than metric manipulation.
4. **Domain/application/framework separation.** This protects real direction-of-dependency semantics.
5. **Contracts remain dependency-light and do not expose implementation objects.** This prevents “contracts” from becoming a laundering layer for internals.
6. **Platform does not depend on business modules.** This directly resists a common escape hatch.
7. **Entrypoints do not reach into module adapters.** This keeps process composition from becoming a parallel business layer.
8. **Mature lint/type/security tooling.** These are standardized checks with understandable failure modes and do not need custom reinvention.

Confidence: **HIGH**, based on direct repo evidence and current normative architecture.

## 7. Weak, harmful, or redundant gates

### 7.1 100/120 file budget — harmful when HARD

The issue is not that file size has zero information. It is that a 120-line cliff has insufficient semantic precision for its current blocking authority.

False-positive examples:

- cohesive declarative module;
- composition root;
- protocol/schema mapping;
- linear orchestration;
- cohesive acceptance/E2E test;
- test fixture world that is easier to understand beside its scenario.

False-negative examples:

- 70-line function with complexity 20+;
- 11 files each below 100 lines that collectively implement one tangled flow;
- chains of wrappers/interfaces/helpers;
- duplicated business logic distributed across modules.

Gaming strategy:

```text
split file
extract forwarding helper
extract test support
move data/constants elsewhere
add interface/factory
```

A literal agent can execute these without understanding the semantic reason for the split.

Second-order effect: over time the repo tends toward smaller physical units with higher navigation cost, making LOC less correlated with cohesion precisely because LOC became the target.

Recommendation: preserve the metric as REVIEW/trend; retire universal 120 blocking authority after approved migration and baseline capture.

### 7.2 Exact filename and source-string fitness

Examples in current connection-surface tests include:

- allowlisting exact top-level entrypoint filenames;
- requiring exact `router.py` and `models.py` files;
- searching source text for exact installer function/signature strings.

These may detect accidental drift, but they are fragile under benign refactor. The protected property is “business transport remains module-owned and composition uses supported surfaces,” not “this exact private filename exists forever.”

Recommendation: rewrite semantic import/type/composition checks; downgrade pure layout assertions to CONTROLLED or remove them where the implementation detail is FLEXIBLE.

### 7.3 Duplicate architecture scans

Cross-module imports and domain/framework boundaries are checked in more than one architecture test file. Duplication can be defensible for critical security invariants but here can create policy drift and inconsistent messages.

Recommendation: one canonical checker implementation per architecture property, fixture-tested, with multiple focused tests only where they exercise genuinely different cases.

## 8. Missing protections

### 8.1 Direct local complexity signal

Current Ruff config does not select `C901`. This is the clearest missing maintainability signal because it measures branching at the function level and directly addresses the “small but complex” failure mode.

Recommendation: add C901 **as warning/report first**, using Ruff's documented default 10 only as a calibration starting point, not a repository law.

### 8.2 Navigability / fragmentation counter-pressure

The repo has strong anti-dumping-ground language but no explicit review signal that says a refactor can regress by increasing reasoning hops.

Recommendation: non-blocking changed-subsystem diagnostic for forwarding-only/tiny-module chains and review guidance. No hard “max files” metric.

### 8.3 Trend baseline

Current CI says the file-budget check passed but does not emit the distributions needed to calibrate thresholds.

Recommendation: non-blocking metrics artifact for file LOC by category, function complexity, module fan-out, file counts, and exception counts.

### 8.4 Traceability IDs

Current architecture docs explain intent well but do not consistently map normative clause -> fitness ID -> checker -> CI job.

Recommendation: adopt the simple traceability matrix in the proposed specification.

### 8.5 Tests for custom fitness-function implementations

The live repository is scanned directly by many architecture tests. The proposed custom HARD checkers should also have controlled positive/negative/boundary fixtures so a buggy checker cannot silently govern architecture.

## 9. Quantitative measurements

### 9.1 What is actually measured in current exact-head evidence

The successful Python quality run reports:

| Measurement | Value |
|---|---:|
| test files | 483 |
| architecture-scope test files | 32 |
| DB-scope test files | 75 |
| E2E-scope test files | 115 |
| historical-scope test files | 17 |
| integration-scope test files | 148 |
| module-scope test files | 90 |
| unit-scope test files | 6 |
| adversarial evidence markers | 78 |
| contract markers | 91 |
| invariant markers | 61 |
| security markers | 27 |
| provenance markers | 37 |
| capacity markers | 17 |
| temporal markers | 8 |

The current dependency policy enumerates 13 business-module names, including deferred `payments`/`dispatch`.

The current file-budget constants are:

```text
effective LOC target = 100
effective LOC hard max = 120
```

### 9.2 Required distributions not asserted by this audit

The prompt correctly asks for:

```text
count, p50, p75, p90, p95, max
```

for effective file LOC, function LOC, cyclomatic complexity, nesting, fan-out, and dependency graph characteristics where reasonably possible.

The current canonical CI **does not publish those distributions**. It reports pass/fail for file budget and repository/test inventory counts. This audit deliberately did not modify CI or production tooling just to manufacture a baseline during the policy-definition phase.

Therefore the following are explicitly **NOT MEASURED / NOT ASSERTED** here:

| Metric | count | p50 | p75 | p90 | p95 | max |
|---|---|---|---|---|---|---|
| effective file LOC by code category | pending | pending | pending | pending | pending | pending |
| function LOC | pending | pending | pending | pending | pending | pending |
| McCabe complexity | pending | pending | pending | pending | pending | pending |
| nesting depth | pending | pending | pending | pending | pending | pending |
| file/module import fan-out distribution | pending | pending | pending | pending | pending | pending |

This missing measurement is itself a decision constraint: **no new numeric HARD threshold should be approved until the baseline report exists and outliers are manually classified.**

## 10. Outlier analysis

Because full percentile distributions are not yet published, this section focuses on manually inspected structural outliers/hotspots rather than pretending to know p95.

### 10.1 Operational Copilot — high fan-out composition hotspot

Classification: **ACCEPTABLE TRADE-OFF / REVIEW-WORTHY**.

Reason: F6 is explicitly an agent-facing composition layer over multiple owners, so higher dependency fan-out is part of its product role. That makes locality more important, not automatically invalid.

Observed pattern: many narrow routers/models/executors/resolvers. Some are meaningful adapters; some are tiny enough that a reader must evaluate whether the file boundary adds ownership value or merely a hop.

### 10.2 `operational_copilot/api/recovery.py`

Classification: **ACCEPTABLE TRADE-OFF / NAVIGABILITY REVIEW**.

The file is essentially a small construction wrapper around a live-capacity reader. It may be justified as an API/composition surface; its smallness is not evidence of quality by itself.

### 10.3 `operational_copilot/adapters/resolution_common.py`

Classification: **ACCEPTABLE TRADE-OFF / REVIEW-WORTHY**.

It owns one generic `require_one()` ambiguity helper. If reused broadly, centralization can be reasonable. If it is one of many such tiny helper modules, the cumulative navigation cost matters more than its LOC.

### 10.4 F5 recovery schedule extraction commit

Commit `c1a132526ef143a21df7033902769ee370335916` moved extend-day validation/payload/fingerprint logic into a new support module and moved substantial test fake/setup code into test support.

Classification: **MIXED / MANUAL REVIEW REQUIRED**.

The production extraction can be defended as a separate pure support responsibility. The test extraction demonstrates the trade-off more sharply: line count of the scenario file falls, but understanding the world now requires another file. Commit evidence alone does not prove the split was caused by the 120 gate, so this audit does **not** assert causation. It does show why metric improvement must not automatically be called maintainability improvement.

### 10.5 Stale `DEFERRED_MODULES` classification

`test_repository_structure.py` includes `delivery` in `DEFERRED_MODULES` while the current ownership map activates Delivery for F3 execution truth.

Classification: **POLICY DRIFT / REVIEW-WORTHY**.

The test happens to stay green because the rule is about baseline modules depending on the set. A stale name can still mislead future maintainers/agents and illustrates why architecture tests need semantic traceability to current ownership contracts.

## 11. False-positive / False-negative analysis

| Rule/signal | Healthy code it may reject | Bad code it may allow | Assessment |
|---|---|---|---|
| contracts-only import | unusual legitimate migration surface | dynamic/service-locator coupling | HARD remains justified with explicit evolution path |
| approved edge policy | legitimate new architecture before docs updated | indirect hidden coupling | HARD against drift; controlled policy evolution |
| cycle detector | essentially none for accepted synchronous model | cycles hidden via dynamic runtime dispatch | HARD justified |
| domain/app framework rules | deliberate architecture replacement | business leakage through unlisted framework/custom types | HARD justified under current model |
| 120 file LOC | large simple/declarative/cohesive tests | small complex/distributed workflows | too many false-positive/negative paths for HARD |
| exact filename allowlist | harmless file rename/split inside same boundary | bad logic inside allowed files | weak proxy for HARD |
| generic filename ban | legitimate technical helper with poor name | business dumping ground with semantic-looking name | useful but naming alone insufficient |
| C901 warning | clear declarative branch table | distributed complexity across helpers | useful warning, not initial HARD |
| navigation diagnostic | legitimate adapter/interface boundary | subtle semantic indirection | review-only appropriate |

## 12. Gaming and Goodhart analysis

### Current 120 target

When file LOC is a blocking target, the predictable optimization is to create more files. As successful optimization proceeds, LOC becomes less informative about responsibility because developers have learned to keep every physical unit below the target regardless of conceptual shape.

This is classic Goodhart pressure:

```text
file LOC signal
 -> hard target
 -> systematic splitting
 -> higher navigation cost / more wrappers
 -> file LOC becomes a weaker cohesion signal
```

### Dependency rules

These are more Goodhart-resistant because the desired target — explicit public dependency surfaces and acyclic directions — is close to the property itself.

Likely gaming moves are still possible:

- re-export internals through contracts;
- move business logic to shared/platform;
- dynamic imports/service locators;
- duplicate logic to avoid dependency.

The existing architecture already blocks some of these. The proposed contract explicitly treats duplication/shared extraction as ownership-review failures rather than acceptable CI-green shortcuts.

### Complexity signal

C901 can be gamed by extracting helpers until each function falls below threshold. Therefore it begins as WARNING and is composition-tested with locality/navigation review.

A lower C901 score is evidence, not proof, of improvement.

## 13. Navigability and fragmentation analysis

Request Engine's module-first architecture is intended to make a capability locatable near its commands, ports, adapters, API, tests, and docs. That design goal is undermined if internal files become so small and numerous that understanding one operation requires extensive jumping.

The risk is highest in orchestration/composition modules such as F5/F6, where many legitimate owners already create unavoidable cross-surface reasoning.

The repository should therefore optimize for **meaningful boundaries**, not minimum file size.

A useful review question for each extraction is:

> After the extraction, can a maintainer understand the operation with fewer or more semantically meaningful context switches?

A separate file is usually healthy when it owns a stable contract, provider/DB adapter, independently changing policy, reusable algorithm, or distinct use case.

A separate file is suspect when it contains only one forwarding call, only exists to hold a few lines displaced by a threshold, or separates test setup from assertions that have no independent lifecycle.

No hard file-hop or module-count threshold is proposed because legitimate bounded-context and adapter boundaries naturally add hops.

## 14. Second-order incentive analysis

### If current file cap remains HARD

Likely long-run architecture:

- more support/helper files;
- more wrapper modules;
- test-world extraction;
- more interfaces/factories to create small units;
- harder grep/navigation across simple flows;
- LOC target looks excellent while conceptual complexity migrates.

### If all size rules are removed with no complexity signal

Likely failure mode:

- genuine god functions/files may accumulate unnoticed;
- reviewers lose an inexpensive outlier signal.

Therefore “no size metric” is also not the proposed design.

### Proposed equilibrium

- direct architectural boundaries remain blocking;
- function complexity becomes visible;
- file size remains visible but cannot force a split by itself;
- navigation/semantic review prevents complexity displacement;
- trend data creates evidence for future calibration;
- legitimate architecture evolution is explicit.

This creates better countervailing incentives than either extreme.

## 15. Minimal sufficient guardrail system

The recommended maintainability/architecture system is deliberately limited to ten fitness functions:

```text
HARD
  FF-DEP-001 contracts-only cross-module imports
  FF-DEP-002 approved dependency direction
  FF-DEP-003 no cycles
  FF-LAYER-001 inward semantic layer boundaries
  FF-PLATFORM-001 technical platform purity
  FF-COMP-001 composition does not bypass module surfaces

WARNING / REVIEW
  FF-CPLX-001 function-level complexity
  FF-FSIZE-001 file-size review signal
  FF-NAV-001 navigability/fragmentation review

INFORMATIONAL
  FF-TREND-001 distributions/fan-out/suppression trend
```

This is sufficient because most other desired properties either:

- are already covered by these rules;
- belong to separate security/product/transaction correctness systems;
- are not reliably automatable.

Adding more metrics for symmetry would increase governance cost without independent signal.

## 16. Important principles intentionally not automated

| Property | Why it matters | Why automation is unreliable | Review guidance |
|---|---|---|---|
| cohesion by reason of change | related behavior should evolve together | static LOC/names do not know business change reasons | ask what changes together and why |
| locality of behavior | reduces reasoning cost | legitimate architectural boundaries add indirection | prefer locality unless a boundary explains the hop |
| abstraction value | prevents ceremony | interface count cannot tell whether substitutability/boundary is real | require conceptual/ownership reason |
| test scenario locality | preserves executable narrative | fixture complexity varies widely | keep world + assertion near unless support is independently reusable |
| semantic maintainability non-regression | resists metric gaming | requires comparison of before/after design | do not call lower metrics improvement if navigation/ownership worsens |
| module ownership choice | preserves evolvability | domain language and lifecycle are contextual | use ownership docs and change reasons |

## 17. Residual risks

Even the proposed system can be gamed or miss bad design.

Bad code that can still pass includes:

- a distributed god workflow whose imports are all formally legal;
- an event bus that hides coupling;
- a service locator invoked dynamically;
- generic contracts that expose too much without importing internals;
- duplicated business policy in two owner modules;
- many tiny adapters that are each locally defensible but cumulatively expensive;
- business semantics hidden in technical-looking code;
- conceptual complexity split across helpers.

Healthy code can still trigger warnings/review signals:

- large declarative modules;
- complex but explicit protocol mapping;
- a central composition root;
- cohesive acceptance tests;
- real adapter boundaries.

Therefore the final system must retain human architecture review. CI green MUST continue to mean “conforms to automated policy,” not “proven maintainable.”

## 18. Adversarial scenario summary

| Scenario | Current system tendency | Proposed system tendency |
|---|---|---|
| A small/complex | may pass file budget | complexity warning |
| B large/simple | hard fails at 121+ if changed/new | review only |
| C 11-file fragmentation | likely passes/rewarded by size | no size reward; navigation review |
| D boundary violation | hard fails | hard fails |
| E shared dumping ground | partly blocked | blocked + explicit ownership review |
| F 350-line cohesive test | hard fails if new/changed | review only |
| G legitimate new edge | fails until allowlist changed | fails until normative architecture evolves |
| H complexity displacement | can pass if files/functions small | numeric change not accepted as semantic proof |
| I suppression pressure | little trend visibility | informational trend triggers rule review |
| J numbers improve/navigation worsens | may appear successful | semantic non-regression rejects claim |
| K literal agent | cheap path often split file | cheap HARD path is fix real boundary; heuristics don't force split |

## 19. Composition test

The dangerous combination today is:

```text
low universal file cap
+
strict dependency boundaries
+
anti-shared-dumping-ground rules
```

Individually, the dependency and shared-layer rules are healthy. Combined with a low hard file cap, however, the developer has fewer safe places to move extracted code and may respond with same-module micro-files or duplication.

The proposed system removes the low numeric cliff while preserving the semantic boundaries, reducing that compound pressure.

Another dangerous future combination would be:

```text
C901 hard threshold
+
file-size hard threshold
+
navigation hard threshold
```

This would create a three-metric optimization maze. The proposal deliberately avoids it: complexity begins WARNING, file size REVIEW, navigability REVIEW.

## 20. Evidence from official tooling and engineering guidance

External sources do not define Request Engine architecture, but they help calibrate claims about metrics:

- Ruff documents `C901` as function-level McCabe complexity and says high complexity makes functions harder to understand/maintain. Its documented default `max-complexity` is 10 when the rule is enabled. This supports using complexity as a local signal, not blindly making 10 a HARD repository constant.
- Linux kernel coding guidance says acceptable function length is inversely related to complexity/indentation and explicitly permits longer conceptually simple functions. This supports semantic precedence over raw size.
- Pylint's `too-many-lines` documentation explicitly describes module lines as a proxy and notes cyclomatic complexity is more fine-grained. Its conventional defaults are far above Request Engine's 120 threshold; that does not make the Pylint default “correct,” but demonstrates that 120 is not an industry constant.
- SonarSource's Cognitive Complexity work explicitly targets understandability of method control flow rather than treating mathematical path count or raw size as maintainability itself.
- Empirical method-size research finds size can correlate with maintenance effort, but published Java method-level thresholds do not directly justify a Python file-level 120 threshold.

Evidence classification: TOOL DOCUMENTATION / INDUSTRY CONVENTION / EMPIRICAL RESEARCH. Confidence that “size is a useful signal”: **MEDIUM-HIGH**. Confidence that “120 Python file lines is an intrinsically correct hard cutoff”: **LOW / unsupported by evidence reviewed**.

References are listed in the constitution.

## 21. Migration plan

No big-bang refactor is required or desired.

### Phase 1 — approve policy

1. review/approve the constitution, this audit, fitness specification, and decision record;
2. promote approved docs into canonical precedence;
3. update current governance/agent instruction wording in the same coherent change.

### Phase 2 — measure without blocking

4. add a deterministic non-blocking structural report;
5. capture file LOC distributions by code category;
6. capture function McCabe distributions;
7. capture module fan-out/file counts;
8. manually classify p95/max and representative outliers.

### Phase 3 — remove harmful authority, not visibility

9. change the 100/120 file budget from universal blocking enforcement to REVIEW/informational reporting;
10. keep temporary measurement of legacy oversized files so the migration does not erase trend visibility;
11. do **not** mechanically merge/split existing files simply to match the new policy.

### Phase 4 — add missing high-signal complexity visibility

12. enable Ruff C901 in non-blocking/reporting or warning mode at the calibrated starting point;
13. inspect false positives and complexity-displacement behavior;
14. only then consider whether any extreme complexity zone deserves HARD enforcement.

### Phase 5 — strengthen custom fitness implementations

15. consolidate duplicated import/layer scans where practical;
16. replace exact filename/source-string assertions with semantic checks;
17. correct stale policy metadata such as Delivery's old deferred classification;
18. add fixture tests for custom HARD checkers;
19. link failures to normative IDs/fitness IDs.

### Phase 6 — observe incentives

20. inspect how human and agent-authored PRs respond to warnings;
21. monitor file count, support/helper proliferation, exceptions, and reviewer dismissals;
22. revise heuristics before ever increasing severity.

## 22. Final adversarial review

**Can structurally bad code still pass?** Yes. Static architecture cannot prove semantic cohesion; residual risk is documented.

**Can healthy code be blocked unnecessarily?** Under current 120 enforcement, yes. Under the proposal, file-size false positives become review rather than failure.

**Do quantitative metrics have too much authority today?** File LOC does relative to direct complexity measurement.

**Does the proposal reward fragmentation?** No direct metric reward remains for splitting a file.

**Does it reward wrappers/premature abstraction?** No; locality and semantic non-regression explicitly reject wrapper-only metric improvements.

**Does it punish declarative code/cohesive tests?** It may surface them for review but does not automatically fail them.

**Can complexity be displaced?** Yes, which is why complexity is not initially HARD and navigation review remains necessary.

**Can dependency restrictions be bypassed?** Some indirect/runtime forms remain possible; shared/platform and contract-leakage controls reduce but do not eliminate them.

**Will literal agents find harmful shortcuts?** They still can, but the cheapest response to the most important HARD gates is substantially closer to the protected architecture than the cheapest response to a low file cap.

**Can architecture evolve?** Yes, through normative decision -> policy -> migration.

**Will suppressions accumulate?** The proposed trend report treats that as evidence about rule quality and keeps heuristic rules non-blocking during calibration.

**Are multiple gates measuring the same risk?** Some current tests are; consolidation is part of migration.

**Is governance itself overengineered?** It is at risk because architecture coverage is already broad. The proposal deliberately adds only one new generic complexity signal plus two non-blocking diagnostics/trends, while consolidating existing checks.

**Could removing a gate make the repository healthier?** Removing the 120 HARD authority while retaining size visibility is expected to improve incentives.

**Are we protecting maintainability or preferred code shape?** The proposed contract explicitly prioritizes change safety, ownership, locality, navigability, and reasoning complexity over shape.

## 23. Final decision

### Current enforcement

**NO** — not yet fully healthy as a default, because a universal 120-line file cap has HARD practical authority despite being a weak proxy and despite the repository's own FLEXIBLE file-split policy.

### Proposed normative contract and fitness system

**YES, WITH EXPLICIT LIMITATIONS**.

The proposal makes following the guardrails a healthier default because:

```text
direct architectural invariants stay strong
local complexity gains visibility
file size loses unjustified blocking authority
cohesion/locality/navigability remain first-class
metric gaming is explicitly rejected
coding-agent behavior is part of the threat model
legitimate architecture evolution has a first-class path
```

Limitations:

- full repository metric distributions must still be measured before quantitative hardening;
- cohesion/locality/module meaning cannot be fully automated;
- dynamic/runtime coupling and distributed conceptual complexity remain residual risks;
- current CI remains unchanged until the proposal is approved and migrated.
