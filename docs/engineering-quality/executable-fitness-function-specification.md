# Request Engine — Executable Fitness Function Specification

> **Status:** PROPOSED. No current test, linter, CI job, or threshold is changed by this document until the proposal is explicitly approved and migrated.
>
> **Audited repository state:** `development@a0eab9f48e91c900e2060a6bbef0812160910b6c`.
>
> **Authority:** this document implements the proposed `engineering-quality-architecture-constitution.md`. If an implementation check conflicts with the constitution, the implementation must be corrected rather than treating the check as accidental policy.

## 1. Classification vocabulary

Every fitness function is classified as one primary signal type:

- **DIRECT INVARIANT** — measures a condition that directly violates accepted architecture.
- **HIGH-SIGNAL STRUCTURAL RULE** — strongly correlates with a real repository risk but may encode controlled shape.
- **HEURISTIC** — useful contextual signal.
- **TREND METRIC** — observes evolution.
- **REVIEW PRINCIPLE** — important but not reliably automatable.
- **INVALID PROXY** — does not adequately measure the claimed property.
- **HARMFUL INCENTIVE** — optimizing the rule can materially worsen design.
- **REDUNDANT SIGNAL** — duplicates another check without meaningful independent coverage.

Automation classes:

- **MACHINE-ENFORCEABLE**
- **MACHINE-DETECTABLE / HUMAN-JUDGED**
- **REVIEW-ONLY**
- **DOCUMENTATION-ONLY**

Severities:

- **HARD**
- **WARNING**
- **REVIEW**
- **INFORMATIONAL**

## 2. Minimal sufficient target system

The proposed target system intentionally stays small:

| ID | Property | Type | Automation | Severity |
|---|---|---|---|---|
| FF-DEP-001 | Cross-module imports use target public contracts | DIRECT INVARIANT | MACHINE-ENFORCEABLE | HARD |
| FF-DEP-002 | Synchronous module edges are explicitly approved | DIRECT INVARIANT | MACHINE-ENFORCEABLE | HARD |
| FF-DEP-003 | Business-module dependency graph is acyclic | DIRECT INVARIANT | MACHINE-ENFORCEABLE | HARD |
| FF-LAYER-001 | Domain/application/contracts preserve inward dependency boundaries | DIRECT INVARIANT | MACHINE-ENFORCEABLE | HARD |
| FF-PLATFORM-001 | Platform stays technical and independent of business modules | DIRECT INVARIANT | MACHINE-ENFORCEABLE | HARD |
| FF-COMP-001 | Entrypoints/composition do not bypass module surfaces into adapters | DIRECT INVARIANT | MACHINE-ENFORCEABLE | HARD |
| FF-CPLX-001 | Function-level control-flow complexity is visible | HEURISTIC | MACHINE-DETECTABLE / HUMAN-JUDGED | WARNING initially |
| FF-FSIZE-001 | File size surfaces potential review candidates | HEURISTIC | MACHINE-DETECTABLE / HUMAN-JUDGED | REVIEW |
| FF-NAV-001 | Fragmentation/navigation hotspots are visible | HEURISTIC | MACHINE-DETECTABLE / HUMAN-JUDGED | REVIEW |
| FF-TREND-001 | Fan-out, suppressions, and structural counts are observable | TREND METRIC | MACHINE-DETECTABLE | INFORMATIONAL |

Existing security, transactional, PostgreSQL, release-history, product-contract, and branch-integration checks are not removed or reclassified by this maintainability specification unless separately named in the migration disposition.

## 3. HARD gate proof obligation

A proposed HARD implementation is acceptable only if its review records all of:

1. exact protected property;
2. concrete risk prevented;
3. whether the property is measured directly;
4. proxy precision if a proxy is used;
5. healthy code that could be rejected;
6. bad code that could still pass;
7. gaming strategy;
8. likely literal coding-agent response;
9. long-term architectural incentive;
10. why HARD rather than WARNING/REVIEW;
11. legitimate exceptions;
12. repository evidence;
13. correct remediation;
14. architecture-evolution path;
15. test strategy for the gate itself.

The following HARD specifications satisfy this obligation at the policy level. Their implementation must still be fixture-tested before migration is complete.

---

## FF-DEP-001 — Public-contract-only cross-module dependencies

**Normative clause:** `ARCH-BOUNDARY-001`.

**Protected property:** module internals remain private; cross-module coupling occurs through intentional stable connection surfaces.

**Risk:** one bounded context couples to another module's domain/application/adapter/API implementation and becomes unable to evolve independently.

**Scope:** handwritten Python below `src/request_engine/modules/*`.

**Signal:** an import edge from module A to module B where the imported target is not B's declared supported contract surface.

**Mechanism/tool:** repository-specific AST dependency scan. Existing `tests/architecture/test_dependency_policy.py` is the strongest current implementation basis.

**Classification:** DIRECT INVARIANT.

**Severity:** HARD.

**Threshold:** binary; any unsupported cross-module internal import is a violation.

**Allowed:** imports from the same module; imports from an explicitly supported target `contracts` package; intentionally approved technical dependencies that are not business-module internals.

**Forbidden:** `module_a -> module_b.domain/application/adapters/api`.

**Legacy:** no silent grandfathering for newly introduced edges. Existing accepted migration surfaces, if any, must be explicit and searchable.

**Exceptions:** only via normative architecture evolution defining the new public surface; not a per-import suppression.

**Failure guidance:** identify caller, target owner, required concept, synchronous consistency need, and smallest stable contract. Warn explicitly against re-exporting internals through `contracts` merely to pass.

**Anti-gaming:** the checker must resolve actual target module and public surface; re-exporting internal objects through contracts should be independently rejected by FF-LAYER-001 contract rules.

**Test strategy:** fixture repository/module pair with (a) valid contract import, (b) invalid domain import, (c) invalid adapter import, (d) same-module import, (e) relative-import boundary case.

**Revisit trigger:** a legitimately approved connection surface other than `contracts`, or a packaging change that makes current AST resolution inaccurate.

**HARD proof summary:**

- direct property: yes;
- false-positive risk: low when the public surface inventory is current;
- false-negative exposure: dynamic imports/service locators remain residual risk;
- likely agent response: use a supported contract or try to re-export; the latter is blocked separately;
- long-term incentive: explicit connection surfaces and ownership;
- why HARD: this is a repository architecture invariant, not a style proxy;
- correct remediation: design/use the correct public contract or intentionally change ownership/architecture.

**Evidence:** DIRECT REPO EVIDENCE — HIGH; NORMATIVE ARCHITECTURE — HIGH.

---

## FF-DEP-002 — Explicit synchronous dependency direction

**Normative clause:** `ARCH-BOUNDARY-002`.

**Protected property:** synchronous module topology is intentional and ownership direction is explicit.

**Risk:** architectural erosion through opportunistic dependencies; a module gradually becomes coupled to capabilities it does not own.

**Scope:** actual cross-business-module Python dependency graph.

**Signal:** actual edge `A -> B` absent from the approved current policy.

**Mechanism/tool:** current module inventory + policy table + AST import graph.

**Classification:** DIRECT INVARIANT for unapproved edges; CONTROLLED architecture shape for the policy table itself.

**Severity:** HARD against drift; policy evolution is explicitly supported.

**Threshold:** binary edge membership.

**Allowed:** approved edges used through public contracts.

**Forbidden:** an unreviewed synchronous edge; widening the allowlist as a mechanical fix.

**Legacy:** accepted current edges are policy, not proof that they are forever ideal. Removal is allowed through architecture evolution.

**Exceptions:** architecture decision updates normative ownership/dependency contract and policy in the same coherent change.

**Failure guidance:** ask why the dependency must be synchronous, which module owns the capability, whether immediate consistency is required, and whether one-way contract/event/outbox composition is more appropriate.

**Anti-gaming:** generic service locator/event bus/shared package must not be a way to hide a real synchronous dependency. Review indirect runtime dependencies when static graph and runtime composition diverge.

**Test strategy:** fixture graph with allowed edge, unapproved edge, new unlisted module, and legitimate policy update case.

**Revisit trigger:** new module, ownership move, or new product capability requiring a new synchronous edge.

**HARD proof summary:**

- direct property: yes, for declared synchronous Python dependencies;
- false-positive risk: low if policy is current;
- false-negative exposure: indirection/dynamic dispatch can hide coupling;
- gaming: service locator/shared abstraction; separately forbidden/reviewed;
- agent response: should design an explicit contract, not edit allowlist mechanically;
- why HARD: accidental dependency direction is an architectural boundary violation;
- evolution: first-class normative policy change.

**Evidence:** DIRECT REPO EVIDENCE — HIGH. Existing `MODULE_DEPENDENCY_POLICY` already provides a precise semantic table.

---

## FF-DEP-003 — Acyclic business-module graph

**Normative clause:** `ARCH-BOUNDARY-003`.

**Protected property:** business ownership can be understood and evolved without circular synchronous dependency.

**Risk:** mutually dependent bounded contexts, hidden shared ownership, initialization/composition problems, and inability to reason about dependency direction.

**Scope:** actual business-module import graph.

**Signal:** graph cycle.

**Mechanism/tool:** deterministic cycle detection over actual module edges.

**Classification:** DIRECT INVARIANT.

**Severity:** HARD.

**Threshold:** any cycle.

**Allowed:** shared transaction/composition when ownership contracts permit it and import direction remains acyclic; event flows may form business feedback loops without forming synchronous implementation cycles.

**Forbidden:** direct or transitive synchronous cycle.

**Legacy:** none expected.

**Exceptions:** none as an ordinary code suppression. If two modules cannot remain acyclic, ownership/module decomposition must be reconsidered.

**Failure guidance:** print the exact cycle and ask which edge represents wrong ownership or wrong connection mode.

**Anti-gaming:** do not permit extracting the common logic into generic business `shared/common` merely to make the graph acyclic.

**Test strategy:** acyclic fixture; direct 2-node cycle; 3-node transitive cycle; disconnected graph.

**Revisit trigger:** only if Request Engine abandons the modular-monolith dependency model through an explicit architecture replacement.

**HARD proof summary:** direct graph invariant, deterministic detection, low false-positive risk, clear remediation, strong long-term architecture incentive.

**Evidence:** DIRECT REPO EVIDENCE — HIGH.

---

## FF-LAYER-001 — Semantic layers remain independent of outer implementation concerns

**Normative clauses:** `ARCH-LAYER-001`, `ARCH-LAYER-002`, `ARCH-CONTRACT-001`.

**Protected property:** domain/application/contracts do not leak transport, persistence, provider, or composition implementation concerns inward or across modules.

**Risk:** framework leakage, persistence-shaped domain, transport-shaped business contracts, concrete-adapter coupling, unstable public contracts.

**Scope:** business `domain`, `application`, and published `contracts` packages.

**Signal:** imports or re-exports of forbidden outer-layer/framework types; direct concrete adapter imports from application; public-contract origin from private implementation packages.

**Mechanism/tool:** AST/import analysis plus narrowly scoped repository-specific origin checks. Avoid exact source-string snapshots when semantic import/type analysis is available.

**Classification:** DIRECT INVARIANT for dependency direction; HIGH-SIGNAL STRUCTURAL RULE for naming conventions.

**Severity:** HARD for dependency direction and implementation-object leakage. Naming spelling alone SHOULD be CONTROLLED/WARNING unless type-role confusion can be detected semantically.

**Threshold:** binary forbidden edge/object exposure.

**Allowed:** plain business values, protocols, semantic commands/queries, framework-free contract values.

**Forbidden:** FastAPI/Pydantic/SQLAlchemy/provider SDK types in business semantic layers where current architecture explicitly excludes them; application importing concrete DB/provider adapters; contracts re-exporting internal objects.

**Legacy:** explicit transition surfaces only; no broad suppressions.

**Exceptions:** architecture contract change if a framework is intentionally adopted as part of a semantic layer, with compatibility/migration evidence.

**Failure guidance:** state which outer concern leaked inward and the expected mapping boundary.

**Anti-gaming:** a transport/persistence type renamed to a business-looking name is still forbidden by origin/dependency analysis.

**Test strategy:** positive/negative fixtures for each layer, re-export case, alias import, and indirect package import.

**Revisit trigger:** new framework boundary or accepted change in layer model.

**HARD proof summary:** dependency direction is explicit and directly detectable; false positives are low when prefix lists are accurate. Exact class suffix rules do not receive the same HARD authority merely because they are easy to assert.

**Evidence:** DIRECT REPO EVIDENCE — HIGH; NORMATIVE ARCHITECTURE — HIGH.

---

## FF-PLATFORM-001 — Platform remains technical

**Normative clause:** `ARCH-PLATFORM-001`.

**Protected property:** shared technical infrastructure remains business-neutral; business policy keeps explicit module ownership.

**Risk:** dependency restrictions are evaded by moving business logic into `platform`, `shared`, `common`, `helpers`, or an equivalent dumping ground.

**Scope:** `src/request_engine/platform` plus repository-level shared-package creation.

**Signal:** platform importing business modules; prohibited generic business-root packages; review signal for business vocabulary/policy appearing in technical shared layers.

**Mechanism/tool:** import graph for direct invariant; package-name/directory checks only as supporting structural rules; review for semantic policy placement.

**Classification:** DIRECT INVARIANT for `platform -> business module`; HIGH-SIGNAL STRUCTURAL RULE for generic dumping-ground creation.

**Severity:** HARD for platform business dependencies. Generic name bans may remain HARD only for the narrow set already normatively prohibited; semantic policy leakage still requires review.

**Threshold:** binary import edge for the direct invariant.

**Allowed:** DB, idempotency, outbox, audit, event, scheduling mechanics, observability, security plumbing.

**Forbidden:** booking/queue/recovery/discovery policy moved into platform to avoid a business dependency.

**Failure guidance:** identify the real business owner. If two modules need the policy, decide ownership and publish a contract; do not duplicate or move it to generic technical code by default.

**Anti-gaming:** absence of a business-module import does not prove business neutrality. Review signals must cover newly introduced technical-sounding packages with domain-specific policy.

**Test strategy:** direct platform->module negative fixture; allowed technical dependency; generic shared business package fixture.

**Revisit trigger:** a deliberately accepted shared kernel with explicit business semantics and ownership.

**HARD proof summary:** direct platform->business dependency is precise and repository-specific; semantic dumping-ground detection remains partly human-judged.

**Evidence:** DIRECT REPO EVIDENCE — HIGH.

---

## FF-COMP-001 — Composition does not bypass supported module surfaces

**Normative clause:** `ARCH-COMPOSITION-001`.

**Protected property:** process entrypoints and bootstrap wire modules rather than becoming a parallel business layer or reaching into concrete internals.

**Risk:** entrypoint-to-adapter coupling, service-locator architecture, duplicated business taxonomy in process code.

**Scope:** `src/request_engine/entrypoints`, `bootstrap`, and module-owned install/composition surfaces.

**Signal:** entrypoint imports of module adapters/internals; business modules importing bootstrap; routers typed directly against concrete persistence/provider implementations where a semantic application surface is required.

**Mechanism/tool:** semantic import analysis.

**Classification:** DIRECT INVARIANT for internal/adapter bypass; exact filename inventories are not the protected property.

**Severity:** HARD for bypass edges. Exact filenames/signature strings SHOULD NOT be HARD unless a separate public contract requires them.

**Threshold:** binary forbidden import/dependency edge.

**Allowed:** entrypoints import module public API/composition surface; module installer constructs adapters and supplies application-facing protocols.

**Forbidden:** entrypoint directly constructs/reaches into module DB/provider internals; business code imports bootstrap as locator.

**Failure guidance:** identify supported composition surface and move construction to the correct owner. Explicitly say not to add the filename to an allowlist as the first repair.

**Anti-gaming:** renaming a direct adapter import or moving it into a generic entrypoint helper must not evade graph analysis.

**Test strategy:** positive public installer import; negative adapter import; nested helper bypass; business->bootstrap import.

**Revisit trigger:** intentional redesign of composition ownership.

**HARD proof summary:** semantic dependency edge directly represents the property; exact file shape does not and is therefore excluded from HARD proof.

**Evidence:** DIRECT REPO EVIDENCE — HIGH. Current `test_connection_surfaces.py` contains both semantic checks worth retaining and shape snapshots that should be decoupled.

---

## FF-CPLX-001 — Function-level control-flow complexity signal

**Normative clause:** Constitution §9.

**Protected property:** locally difficult reasoning surfaces are detected earlier than file-size proxies can detect them.

**Risk:** a small file/function with many branches/nesting paths passes current size gates while remaining difficult to understand and modify.

**Scope initially:** handwritten production Python under `src/request_engine`; test inclusion should be separately calibrated because scenario code has different structure.

**Signal:** McCabe/cyclomatic complexity per function. Cognitive complexity MAY be evaluated later if a mature low-cost Python tool fits the repository.

**Mechanism/tool:** prefer existing Ruff `C901` rather than a custom parser. Current Ruff configuration does not enable C901.

**Classification:** HEURISTIC.

**Severity:** WARNING during initial calibration.

**Threshold:**

- **candidate initial warning zone:** `C901 > 10`, because Ruff's documented default is 10;
- **HARD zone:** none approved yet;
- repository p50/p75/p90/p95/max MUST be measured before considering stronger enforcement.

The Ruff default is a tooling convention, not proof that 10 is the correct Request Engine threshold.

**Allowed:** a branching function may remain above the warning when the branches represent a clear declarative mapping or when extraction would worsen locality; reviewer records why.

**Forbidden remediation:** slicing one conceptual decision tree into forwarding helpers solely to lower each helper's measured score.

**Legacy:** initial observation applies to all scoped code without blocking; later ratchets only after outlier review.

**Exceptions:** warning disposition in review; no suppression bureaucracy during calibration.

**Failure guidance:** report function, score, branches if tool supports them, and say to simplify decision structure/side-effect mix while preserving locality. Explicitly warn that helper extraction without reduced conceptual complexity is not a sufficient fix.

**Anti-gaming:** combine review with FF-NAV-001; never declare a refactor improved solely because per-function C901 fell.

**Test strategy:** representative low-complexity function, high-branch function, declarative case/match function, and complexity-displacement example.

**Revisit trigger:** after at least one representative development interval with measured distributions and false-positive examples.

**Evidence:** TOOL DOCUMENTATION — HIGH; ENGINEERING JUDGMENT — MEDIUM. Ruff documents C901 as function-level McCabe complexity and default max 10.

---

## FF-FSIZE-001 — File-size review signal

**Normative clause:** Constitution §10.

**Protected property:** unusually large reasoning containers are surfaced for review without equating size with bad architecture.

**Risk:** genuinely overloaded files go unnoticed; conversely, a hard low cap creates fragmentation and wrappers.

**Scope:** report separately for production, tests, migrations/configuration, and scripts. Generated code is excluded or separately reported.

**Signal:** effective code-bearing file LOC.

**Mechanism/tool:** reuse or simplify the current effective-line counter, but change its authority after approval.

**Classification:**

- file LOC itself: HEURISTIC;
- current universal 120-line blocking limit as architecture proxy: HARMFUL INCENTIVE / INVALID PROXY for HARD enforcement.

**Severity:** REVIEW.

**Threshold:** no new blocking threshold approved.

Before implementation finalizes review zones, measure by code category:

```text
count, p50, p75, p90, p95, max
```

The existing `100 target / 120 hard` values MUST NOT be copied into the new contract merely because they already exist.

An extreme-outlier protection MAY later be proposed only after manual inspection demonstrates a region with materially higher risk and low false-positive pressure.

**Allowed:** cohesive large declarative module; composition root; schema/protocol mapping; cohesive acceptance test.

**Review-worthy:** large file with mixed responsibilities, high local complexity, unrelated side effects, or ownership diversity.

**Forbidden remediation:** split solely to get under a number; extract wrappers/test-support files that increase navigation without independent responsibility.

**Legacy:** the existing >120 ratchet remains current policy only until migration. The target model does not grandfather weak-proxy debt forever; it first reclassifies the signal, then measures it.

**Exceptions:** not needed for a REVIEW signal. If an extreme future HARD cap exists, exception policy must be explicit and expiring.

**Failure/review guidance:** ask whether a separable responsibility exists and whether the split shortens the reasoning path. Do not say merely `N > threshold`.

**Anti-gaming:** no CI reward for reducing file LOC alone. Metric reports SHOULD include file-count/navigation context where practical.

**Test strategy:** counter correctness fixtures (blank/comment/docstring/string); large simple file; small complex file; legacy delta; split-with-same-total behavior for reporting.

**Revisit trigger:** measured outlier distribution changes materially; repeated reviewer dismissals; repeated legitimate exceptions if any blocking zone is introduced.

**Evidence:** DIRECT REPO EVIDENCE — HIGH that 100/120 currently blocks changed files; EMPIRICAL/TOOL evidence — MEDIUM that size is a useful signal; HIGH confidence that no repository-specific evidence currently proves 120 as a semantic cliff.

---

## FF-NAV-001 — Navigability and fragmentation diagnostic

**Normative clauses:** Constitution §§7–8.

**Protected property:** understanding a cohesive operation does not require unnecessary file/module/interface hops.

**Risk:** micro-files, forwarding wrappers, helper chains, test-support fragmentation, and abstraction depth hide rather than reduce conceptual complexity.

**Scope:** changed subsystems, initially diagnostic rather than repository-wide blocking.

**Signals, only in combination:**

- very small one-function modules;
- functions that only forward to one dependency;
- re-export-only files;
- delegation depth;
- number of files traversed for an operation;
- interface with one implementation and no boundary/substitution reason;
- post-refactor file-count increase without reduced responsibility/complexity.

**Mechanism/tool:** lightweight report or review checklist. Do not create an opaque composite score.

**Classification:** HEURISTIC.

**Severity:** REVIEW.

**Threshold:** no universal blocking threshold.

**Allowed:** small file that is a meaningful public boundary, framework adapter, provider adapter, generated mapping, or distinct independently changing responsibility.

**Review-worthy:** chains of forwarding modules, one-use wrappers, artificial helper/support files created solely to satisfy another metric.

**Failure guidance:** no blocking failure by default. Report the suspected reasoning path and ask whether consolidation would preserve boundaries while improving locality.

**Anti-gaming:** this diagnostic is specifically the counter-pressure against size/complexity metric gaming. It MUST NOT itself become a target such as “maximum 4 files per operation.”

**Test strategy:** sample forwarding chain, legitimate adapter boundary, one-function public contract adapter, and artificial 11-file split scenario.

**Revisit trigger:** a stable, repository-specific structural pattern emerges with high signal and low legitimate exception rate.

**Evidence:** DIRECT REPO EVIDENCE — MEDIUM/HIGH for observed micro-file patterns; causal claim that file budget created them — MEDIUM at most without historical attribution.

---

## FF-TREND-001 — Structural trend report

**Normative clause:** Constitution §§13–14.

**Protected property:** governance decisions can be calibrated from repository evolution rather than anecdotes.

**Risk:** fan-out, suppressions, module count, file count, or exception pressure grows silently until it becomes architectural debt.

**Scope:** repository and changed subsystem.

**Signals:**

- per-module fan-out/fan-in;
- module count;
- production/test file count;
- file LOC distribution by category;
- function complexity distribution;
- suppressions/exemptions count;
- warning/review dismissal patterns if recorded.

**Mechanism/tool:** non-blocking CI artifact/report.

**Classification:** TREND METRIC.

**Severity:** INFORMATIONAL.

**Threshold:** none by default.

**Anti-gaming:** trends MUST NOT become hidden quality scores. A rise is a prompt to inspect cause, not automatic evidence of regression.

**Test strategy:** deterministic report fixture and schema test.

**Revisit trigger:** a trend consistently predicts concrete defects or review problems and can justify a separate high-signal rule.

---

## 4. Current-gate disposition

This section records how the existing engineering-quality mechanisms should be treated after proposal approval. It does not change them yet.

| Current mechanism | Current effect | Proposed classification | Disposition |
|---|---|---|---|
| `check_python_file_budget.py` target 100 / hard 120 | blocks changed/new `src` and `tests` files >120; ratchets existing oversized files | HEURISTIC made into HARMFUL HARD target | replace blocking authority with FF-FSIZE-001 review/trend after baseline capture |
| Ruff `E,F,I,UP,B,ASYNC,SIM` | generic lint | HIGH-SIGNAL generic tooling | preserve |
| Ruff format | deterministic formatting | DIRECT style conformance | preserve; outside architecture semantics |
| Pyright strict | static type consistency | HIGH-SIGNAL generic tooling | preserve |
| secret/security/dependency audits | security quality | HIGH-SIGNAL/direct security controls | preserve; outside maintainability scope |
| `test_dependency_policy.py` contracts-only | blocks module-internal coupling | DIRECT INVARIANT | preserve as FF-DEP-001 |
| explicit module dependency policy | blocks unapproved edges | DIRECT INVARIANT | preserve as FF-DEP-002 |
| dependency cycle detector | blocks cycles | DIRECT INVARIANT | preserve as FF-DEP-003 |
| domain/application/contracts import restrictions | blocks layer leakage | DIRECT INVARIANT | preserve/consolidate as FF-LAYER-001 |
| `platform` cannot import modules | blocks business dependency in technical layer | DIRECT INVARIANT | preserve as FF-PLATFORM-001 |
| entrypoints cannot import module adapters | blocks composition bypass | DIRECT INVARIANT | preserve as FF-COMP-001 |
| duplicate contracts/domain checks across architecture files | same risk enforced in multiple places | REDUNDANT SIGNAL | consolidate where behavior overlaps |
| exact entrypoint filename allowlist | blocks unlisted private composition filenames | CONTROLLED shape / potentially INVALID PROXY | rewrite semantically or downgrade |
| exact `router.py`/`models.py` existence | freezes implementation filenames | FLEXIBLE shape proxy | remove from HARD architecture role unless public tooling requires exact path |
| exact source-string installer/signature checks | detects convention but is refactor-fragile | HIGH-SIGNAL intent with weak mechanism | replace with semantic import/type/behavior proof where needed |
| generic business dumping-ground filename bans | protects ownership but is name-based | HIGH-SIGNAL STRUCTURAL RULE | keep narrow; supplement with semantic review, never assume naming alone proves ownership |
| branch integration lane | serialized repository process invariant | DIRECT PROCESS INVARIANT | preserve; not a maintainability metric |

## 5. Redundant-signal policy

Two checks MAY overlap when they protect materially different failure modes or provide defense in depth for a critical safety invariant. Otherwise duplicated architecture assertions SHOULD be consolidated.

Current examples requiring implementation-phase consolidation review:

- contracts-only imports appear in both dependency-policy and repository-structure tests;
- domain/framework restrictions appear in multiple architecture files;
- layer/transport boundaries are partly duplicated between dependency and governance tests.

The goal is one obvious authoritative fitness function per architectural property, plus targeted fixture tests for that function.

## 6. Threshold register

### File effective LOC

| Field | Proposed policy |
|---|---|
| metric | code-bearing physical lines per file |
| scope | separate production/tests/migrations/scripts/generated categories |
| purpose | review signal for overloaded responsibility |
| normal zone | NOT YET CALIBRATED |
| review zone | NOT YET CALIBRATED; existing 100 SHOULD NOT be assumed normative |
| hard zone | NONE APPROVED |
| repository distribution | current canonical CI does not publish p50/p75/p90/p95/max; must be measured before migration finalization |
| evidence | size is useful as a signal; no evidence of a semantic cliff at 120 |
| false-positive risk | HIGH under universal low hard cap: declarative modules, cohesive tests, composition/configuration |
| gaming risk | HIGH: splitting, wrappers, support-file extraction |
| legacy treatment | current ratchet remains until migration; target policy re-measures rather than permanently grandfathering |
| revisit trigger | measured distributions + inspected outliers; repeated review findings; any proposal for extreme hard cap |

### Function McCabe complexity

| Field | Proposed policy |
|---|---|
| metric | per-function McCabe/cyclomatic complexity |
| scope | production Python first |
| purpose | detect local control-flow reasoning difficulty |
| normal zone | NOT REPOSITORY-CALIBRATED |
| review/warning zone | candidate `>10` during calibration because Ruff documents 10 as default |
| hard zone | NONE APPROVED |
| repository distribution | MUST be measured before hardening |
| evidence | direct tool documentation + established control-flow interpretation |
| false-positive risk | declarative branching/match tables and protocol mapping |
| gaming risk | helper extraction / complexity displacement |
| legacy treatment | observation first; no forced cleanup campaign |
| revisit trigger | representative trend data and manually classified outliers |

### Function LOC

No hard threshold is proposed. It MAY be reported alongside complexity/nesting. Method-size empirical research is informative but language- and method-specific; it does not justify copying a Java line threshold into Python policy.

### Navigability / delegation

No numeric threshold is proposed. Any later threshold requires a repository-specific validation study because legitimate adapter and bounded-context boundaries naturally add hops.

## 7. HARD-gate failure UX template

A custom architecture failure SHOULD resemble:

```text
FF-DEP-001 / ARCH-BOUNDARY-001

WHAT: cross-module import bypassed the target public contract.
WHERE: src/request_engine/modules/<caller>/... -> request_engine.modules.<target>.adapters...
RISK: caller now couples to target implementation ownership.
CORRECT REMEDIATION: consume/design the smallest supported target contract, or revise ownership deliberately.
DO NOT: re-export the adapter through contracts, move the logic to shared/platform, or suppress the check.
EVOLUTION: update the normative ownership/dependency contract first if the new connection is intentional.
```

A heuristic warning SHOULD explicitly state that the numeric value is a signal and that metric reduction alone is not proof of maintainability improvement.

## 8. Fitness-function self-tests

Every custom HARD gate SHOULD expose testable checker logic rather than only scanning the live repository from one monolithic test.

Minimum practical fixture coverage:

```text
positive case
negative case
boundary/alias case
failure-message assertion
```

For graph checks add cycle and new-module cases. For import checks add aliases and relative imports. For ratchets/reporters add baseline/new/decrease cases.

A blocking custom checker without controlled negative fixtures is governance debt.

## 9. Architecture evolution protocol

When a legitimate feature requires a currently forbidden edge or composition path:

1. identify the current normative clause and risk;
2. document the new ownership/connection model;
3. determine whether the old invariant is superseded or only broadened;
4. update normative docs first in the coherent change;
5. update the fitness-function policy/table;
6. add positive and adversarial proof for the new boundary;
7. migrate implementation;
8. run exact-head CI.

A policy-table edit without the architecture reasoning is not an approved exception.

## 10. Traceability matrix

| Normative ID | Property | Enforcement class | Fitness IDs |
|---|---|---|---|
| ARCH-BOUNDARY-001 | modules consume other modules through declared contracts | AUTOMATED | FF-DEP-001 |
| ARCH-BOUNDARY-002 | synchronous module edges are explicitly approved | AUTOMATED + architecture-decision evolution | FF-DEP-002 |
| ARCH-BOUNDARY-003 | business dependency graph remains acyclic | AUTOMATED | FF-DEP-003 |
| ARCH-LAYER-001 | domain remains independent of outer implementation concerns | AUTOMATED | FF-LAYER-001 |
| ARCH-LAYER-002 | application remains independent of concrete adapters/transport | AUTOMATED | FF-LAYER-001 |
| ARCH-CONTRACT-001 | public contracts do not expose implementation objects | AUTOMATED/PARTIALLY AUTOMATED | FF-LAYER-001 |
| ARCH-PLATFORM-001 | platform is technical, not business ownership | AUTOMATED + REVIEW | FF-PLATFORM-001 |
| ARCH-COMPOSITION-001 | composition roots do not bypass module surfaces | AUTOMATED | FF-COMP-001 |
| ARCH-OWNERSHIP-001 | one obvious business owner; no shared dumping ground | PARTIALLY AUTOMATED/REVIEW | FF-PLATFORM-001, FF-NAV-001 |
| Constitution §6 | cohesion by responsibility/reason to change | REVIEW-ENFORCED | FF-FSIZE-001, FF-NAV-001 supporting only |
| Constitution §7 | locality of behavior | REVIEW-ENFORCED | FF-NAV-001 |
| Constitution §8 | navigability | REVIEW-ENFORCED | FF-NAV-001, FF-TREND-001 |
| Constitution §9 | local reasoning complexity | PARTIALLY AUTOMATED | FF-CPLX-001 |
| Constitution §10 | file size is secondary signal | PARTIALLY AUTOMATED | FF-FSIZE-001 |
| Constitution §14 | metrics resist Goodhart/coding-agent gaming | REVIEW-ENFORCED | all heuristic gate reviews |

## 11. Required adversarial simulations

### A — small but complex

**Scenario:** 85-line function, cyclomatic complexity 22, multiple side effects.

- principles: local complexity > superficial file size;
- automated result: FF-CPLX-001 warns; FF-FSIZE-001 may not signal;
- review: side-effect diversity and nesting/branches;
- correct remediation: simplify decision structure, separate genuinely independent side effects, clarify state transitions;
- unhealthy shortcut rejected: split into forwarding helpers solely to get each score down;
- incentive: healthy.

### B — large but simple

**Scenario:** 280-line cohesive declarative module, complexity near 1.

- automated result: no boundary failure; file-size REVIEW only;
- correct remediation: none required if cohesion/locality are strong;
- incentive: does not force fragmentation.

### C — artificial fragmentation

**Scenario:** one simple flow split across 11 files to satisfy LOC.

- automated result: no reward from FF-FSIZE-001 because it is non-blocking; FF-NAV-001 surfaces fragmentation;
- correct remediation: consolidate behavior that changes/reasons together without crossing a real boundary;
- incentive: healthy.

### D — real boundary violation

**Scenario:** one bounded context imports another's adapter/domain internals.

- automated result: FF-DEP-001 HARD fails; FF-DEP-002 may also fail if edge unapproved;
- correct remediation: supported contract or deliberate ownership change;
- incentive: strong and direct.

### E — shared dumping ground

**Scenario:** business logic moves into `shared/utils` to evade dependency restrictions.

- automated result: FF-PLATFORM-001/generic-root structural checks where applicable; architecture review otherwise;
- correct remediation: assign business ownership and publish an explicit contract;
- incentive: avoids loophole.

### F — cohesive large test

**Scenario:** 350-line acceptance test with tightly related world/scenarios.

- automated result: file-size REVIEW, not failure;
- correct remediation: keep cohesive unless reusable fixture/support has an independent reason to change;
- incentive: preserves executable locality.

### G — legitimate architecture evolution

**Scenario:** approved new dependency direction.

- automated result before policy change: FF-DEP-002 fails as designed;
- correct remediation: update normative architecture -> policy -> implementation -> exact-head proof;
- incentive: evolution is explicit rather than bypassed.

### H — complexity displacement

**Scenario:** complex function split into ten helpers without reducing conceptual complexity.

- automated result: per-function complexity may improve; FF-NAV-001 review and semantic non-regression rule prevent declaring victory automatically;
- correct remediation: reduce decision/side-effect complexity or restore locality;
- incentive: no automatic reward for score displacement.

### I — exception pressure

**Scenario:** suppressions grow repeatedly.

- automated result: FF-TREND-001 reports growth;
- review: determine whether code is exceptional or the rule is wrong;
- incentive: recalibrate governance before building suppression bureaucracy.

### J — quantitative improvement / semantic regression

**Scenario:** LOC and complexity values fall, but understanding now requires eight additional files.

- automated result: numeric signals improve but no maintainability-success state is emitted; FF-NAV-001 review triggers when detectable;
- normative result: semantic non-regression rule rejects the claim of improvement;
- incentive: healthy.

### K — literal coding agent

**Scenario:** agent optimizes only for green CI.

- HARD boundary failures require fixing explicit ownership/dependency edges;
- file size is not a blocking target, so mechanical file splitting has no direct CI reward;
- complexity warning tells the agent not to create wrapper chains and remains review-calibrated;
- correct default path is more aligned with the protected property than current universal 120-line blocking pressure.

## 12. Composition test

The system MUST be evaluated as one incentive system, not a list of individually reasonable rules.

Key composition constraints:

- FF-CPLX-001 + FF-FSIZE-001 MUST NOT imply “extract until both numbers are low.”
- FF-DEP-* + FF-PLATFORM-001 MUST NOT encourage duplicated business logic; ownership review is the required escape path.
- FF-DEP-* MUST NOT force a correctly atomic local transaction into asynchronous messaging merely for visual purity.
- FF-NAV-001 MUST NOT become a hard “maximum files per operation” target.
- generic naming bans MUST NOT substitute for semantic ownership review.

## 13. Adversarial green-CI test and residual risk

Bad architecture can still pass any realistic static system. Residual cases include:

- distributed god workflows composed through formally valid contracts;
- event-bus abuse;
- service locators/dynamic imports invisible to simple static scans;
- overly generic contract DTOs that hide coupling;
- duplicated business logic that has no forbidden import edge;
- business policy in technical-looking code without direct module imports;
- many tiny modules where each import is technically legal;
- complexity distributed across helpers.

Therefore:

> **Green CI proves conformance to automated policy, not maintainability.**

Review principles for cohesion, locality, ownership meaning, and navigability remain necessary.

## 14. Inverse test — healthy code must remain admissible

The proposed system intentionally permits, subject to review rather than automatic failure:

- large declarative modules;
- cohesive integration/acceptance tests;
- composition roots;
- schema/protocol mappings;
- linear orchestration;
- legitimate technical shared primitives;
- single-implementation interfaces when a real architectural boundary requires the protocol.

If future thresholds begin rejecting these systematically, severity/scope/mechanism MUST be revisited before developers reshape healthy code around the metric.

## 15. Final policy decision

**YES, WITH EXPLICIT LIMITATIONS** — the proposed fitness-function set makes adherence a genuinely healthier default than the current size-dominated rule set, provided:

1. current 100/120 enforcement is not simply copied into the new policy;
2. repository distributions are measured before heuristic thresholds are hardened;
3. custom HARD checks receive fixture tests and semantic failure messages;
4. shape snapshots are rewritten around protected properties where practical;
5. cohesion/locality/navigability remain explicit human-review responsibilities;
6. architecture evolution remains a first-class path.

The proposal intentionally does not claim that CI can prove maintainability.
