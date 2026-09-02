# Request Engine — Engineering Quality & Architecture Constitution

> **Status:** PROPOSED. This document becomes normative only after explicit approval and promotion through `docs/README.md` precedence. Until then, existing repository governance and CI remain authoritative.
>
> **Audited repository state:** `development@a0eab9f48e91c900e2060a6bbef0812160910b6c`.
>
> **Purpose:** define the engineering properties that quality gates are allowed to protect. Tests, linters, static analysis, and CI implement this policy; they do not create architecture policy by accident.

## 1. North star

The normal path to green CI SHOULD coincide, for the important cases, with the path toward code that is:

- cohesive;
- locally understandable;
- navigable;
- low in genuine reasoning complexity;
- explicitly encapsulated;
- correctly owned;
- easy to evolve deliberately.

A quality gate is unhealthy if the easiest way to satisfy it is to fragment cohesive behavior, add forwarding wrappers, introduce abstractions without ownership value, duplicate business logic, or move policy into a generic technical layer.

The governing principle is:

> **Code SHOULD remain cohesive, navigable, low in genuine complexity, and protected by explicit architectural boundaries. File size is a secondary signal that may justify review; it is not an architectural invariant.**

## 2. Authority order

Engineering authority flows in this order:

```text
engineering intent
    -> normative quality and architecture contract
    -> executable fitness-function specification
    -> implementation in tests / linters / static analysis / CI
```

It MUST NOT flow in reverse merely because a check already exists.

An existing CI assertion is evidence about previously accepted policy. It is not proof that the policy is still well calibrated.

When documented, observed, and enforced architecture disagree, the disagreement MUST be reviewed rather than silently choosing whichever form is easiest to automate.

## 3. Design priority

Quality governance MUST prioritize, in order:

1. real architectural and ownership boundaries;
2. genuinely difficult local reasoning complexity;
3. cohesion and locality of behavior;
4. navigability;
5. quantitative metrics as supporting signals;
6. no additional rule unless it materially improves one of the preceding properties.

A lower-priority metric MUST NOT override a higher-priority semantic property.

## 4. Semantic precedence and non-regression

A change MUST NOT be classified as a maintainability improvement solely because LOC, function count, complexity score, module count, fan-out, or another quantitative metric improves when cohesion, locality, navigability, ownership clarity, or architectural integrity materially worsens.

This applies especially to:

- file extraction;
- function extraction;
- interface extraction;
- module extraction;
- dependency inversion;
- shared abstraction creation.

An extraction SHOULD have a conceptual reason: independent responsibility, stable boundary, distinct ownership, reusable policy, or a materially clearer reasoning unit. A numeric threshold alone is not a conceptual reason.

## 5. Request Engine architectural invariants

Request Engine is a modular monolith organized **module first, layer second**. The following are candidate HARD invariants because they are explicit, repository-specific boundaries and are detectable with high precision.

### ARCH-BOUNDARY-001 — cross-module public surfaces

A business module MUST consume another business module only through that module's declared supported contract surface.

A module MUST NOT import another module's `domain`, `application`, `adapters`, or `api` internals.

### ARCH-BOUNDARY-002 — approved dependency direction

A synchronous business-module dependency MUST be explicitly approved in the current dependency policy.

Changing the approved graph is an architecture decision, not a mechanical allowlist repair.

### ARCH-BOUNDARY-003 — acyclic business graph

The actual synchronous business-module dependency graph MUST remain acyclic.

A cycle MUST be resolved by reviewing ownership or connection direction. It MUST NOT be hidden behind a service locator, generic shared package, or re-export facade.

### ARCH-LAYER-001 — domain independence

Business `domain` code MUST remain independent of transport frameworks, persistence frameworks/drivers, concrete adapters, bootstrap, and process entrypoints.

### ARCH-LAYER-002 — application independence

Business `application` code MUST remain independent of concrete database/provider adapters and HTTP transport concerns. Application ports and semantic contracts MAY define the capabilities required by outer adapters.

### ARCH-CONTRACT-001 — public contracts remain dependency-light

Published module contracts MUST NOT re-export domain, application, persistence, provider, or transport implementation objects as a shortcut.

### ARCH-PLATFORM-001 — technical platform ownership

`platform` MUST remain a technical cross-cutting layer and MUST NOT become a home for business policy or import business modules.

### ARCH-COMPOSITION-001 — composition roots stay composition roots

Entrypoints/bootstrap MAY construct concrete implementations, but business code MUST NOT use bootstrap or process entrypoints as service locators. Process composition MUST NOT reach directly into module persistence/provider internals when a supported module composition surface exists.

### ARCH-OWNERSHIP-001 — business truth has one obvious owner

A business capability SHOULD have one obvious semantic owner. Business logic MUST NOT be moved to `shared`, `common`, `utils`, `platform`, or equivalent merely to evade dependency rules.

If two modules appear to require the same business logic, ownership MUST be reviewed before duplication or generic extraction is accepted.

## 6. Cohesion policy

Cohesion is defined by responsibility and reason to change, not by line count.

Code is cohesive when the behavior, invariants, and data needed for one understandable responsibility change together and can be reasoned about together.

Review SHOULD ask:

- Do these elements change for the same business or technical reason?
- Is one understandable responsibility present?
- Are unrelated side effects or policy decisions mixed?
- Was related behavior separated only to satisfy tooling?
- Would consolidation reduce navigation without violating a real boundary?

The repository explicitly rejects these equations:

```text
small file == cohesive
many files == modular
many interfaces == decoupled
low LOC == maintainable
```

Cohesion is primarily **MACHINE-DETECTABLE / HUMAN-JUDGED**. Static signals MAY identify candidates for review, but CI MUST NOT claim to prove cohesion from a size threshold.

## 7. Locality of behavior

Behavior required to understand a cohesive operation SHOULD remain as local as practical unless a real architectural boundary justifies separation.

The repository SHOULD avoid creating navigation cost through:

- one-function forwarding modules without boundary meaning;
- wrapper chains;
- helper proliferation;
- re-export chains;
- unnecessary factories;
- unnecessary interfaces;
- deep delegation;
- split test worlds whose setup and assertions must be read together.

A boundary is a valid reason for indirection. A metric is not.

Locality is primarily **REVIEW-ONLY**, with optional non-blocking diagnostics.

## 8. Navigability policy

A maintainer SHOULD be able to locate a capability and follow its important behavior through a short, semantically meaningful path.

Useful diagnostic signals MAY include:

- files traversed for one operation;
- directories crossed;
- delegation depth;
- interfaces resolved;
- forwarding-only modules;
- cross-module hops.

These signals are not currently precise enough to justify universal HARD thresholds in Request Engine.

A design that requires eleven files to understand a simple operation is not automatically superior to a cohesive three-file design merely because each file is smaller.

## 9. Complexity philosophy

Complexity SHOULD be measured close to the unit where a maintainer reasons: normally a function/method or a bounded orchestration path.

Relevant signals include, when independently useful:

- cyclomatic complexity;
- cognitive complexity;
- nesting depth;
- branch count;
- exception/control-flow paths;
- side-effect diversity;
- function size;
- dependency count.

The repository SHOULD distinguish:

```text
large but simple
```

from:

```text
small but difficult
```

A 280-line declarative module with near-linear control flow MAY be healthier than a 70-line function with high branching, deep nesting, and several unrelated side effects.

No complexity threshold becomes HARD until repository distributions and outliers are measured and the HARD-gate proof obligation is satisfied.

## 10. File-size philosophy

**File size is a secondary maintainability signal, not an architectural invariant and not a direct measurement of cohesion.**

File LOC MAY be used as:

- a review trigger;
- a warning;
- an extreme-outlier diagnostic;
- a legacy trend/ratchet signal if independently justified;
- an informational repository trend.

File LOC MUST NOT imply:

```text
large file -> split file
```

The correct question is:

> Is there a conceptually separable responsibility that should have its own ownership or boundary?

If the answer is no, splitting MAY reduce maintainability.

The current `100` effective-line target and `120` effective-line blocking limit are therefore **not accepted by this proposed constitution as a HARD architecture invariant**. They remain current enforcement until the approved migration changes them; they MUST NOT be removed before the replacement policy and migration are accepted.

## 11. Function-size philosophy

Function size can be a more localized signal than file size, but it remains a proxy.

A long function SHOULD be reviewed in combination with control-flow complexity, nesting, branches, side effects, and conceptual responsibility.

The repository MUST NOT require trivial wrapper extraction merely to reduce a function's line count.

## 12. Different code types require different policies

A single numeric policy MUST NOT be assumed appropriate for all of:

- domain logic;
- application orchestration;
- infrastructure adapters;
- transport code;
- composition roots;
- contracts/schemas;
- configuration;
- migrations;
- scripts;
- unit tests;
- integration/acceptance/E2E tests;
- fixtures;
- generated code.

A cohesive 350-line acceptance test MAY be preferable to five files that separate the world setup, sequence, and assertions without an independent reason to change.

Declarative schemas/configuration and composition roots MAY legitimately be larger than decision-heavy domain functions.

## 13. Quantitative metrics policy

Metrics are evidence, not goals.

Before a threshold is adopted, its proposal MUST document:

- metric and scope;
- protected property;
- repository distribution;
- inspected outliers;
- normal/review/hard zones;
- false-positive risk;
- false-negative risk;
- gaming strategy;
- likely coding-agent response;
- legacy treatment;
- revisit trigger.

Percentiles describe the repository. They do not become policy automatically.

False precision MUST be avoided. If `200`, `220`, and `250` do not represent materially different risk, the contract MUST NOT pretend that one is scientifically correct.

## 14. Goodhart and coding-agent policy

Coding agents are part of the threat model.

For each enforceable metric, reviewers MUST ask:

> What is the cheapest literal change an agent would make to turn CI green?

Guardrails MUST be designed so that the cheapest normal repair tends to improve the protected property.

Known gaming patterns include:

- mechanical file splitting;
- forwarding wrappers;
- interface/factory proliferation;
- generic helper extraction;
- runtime/dynamic import bypasses;
- suppression comments;
- duplicated logic;
- moving business policy into technical shared code;
- distributing conceptual complexity across many helpers.

A measure that ceases to correlate with the goal once developers optimize for it MUST NOT dominate enforcement.

## 15. Enforcement philosophy

### HARD

Use only when the property is precise, stable, directly detectable or supported by a high-precision proxy, false positives are rare, legitimate exceptions are unusual, and correct remediation is clear.

Every HARD rule MUST satisfy the proof obligation in the executable fitness-function specification.

### WARNING

Use for a strong signal with legitimate contextual exceptions.

### REVIEW

Use when anomaly detection is useful but semantic judgment is required.

### INFORMATIONAL

Use for trend visibility and calibration.

`REVIEW` MUST NOT be upgraded to `HARD` merely because a tool can block CI.

## 16. Custom-tooling policy

Prefer mature tooling for generic properties such as:

- formatting;
- lint;
- typing;
- generic complexity;
- generic dependency graph analysis.

Use custom fitness functions for repository-specific semantics such as:

- module ownership;
- supported contract surfaces;
- allowed dependency direction;
- Request Engine-specific composition boundaries.

A custom blocking gate MUST justify permanent maintenance cost and SHOULD have positive, negative, and boundary fixtures when practical.

## 17. Failure UX

A blocking failure SHOULD report:

```text
WHAT failed
WHERE it failed
WHICH normative clause is involved
WHAT risk the clause protects
WHY the risk matters
CORRECT remediation
ANTI-PATTERN remediation to avoid
HOW the architecture can intentionally evolve
```

A message that only says `126 > 120` teaches optimization of the measurement instead of the design.

## 18. Exceptions

Exceptions MUST be explicit, rare, searchable, reviewable, and justified.

When practical they SHOULD be owned, dated, and expiring.

Repeated legitimate exemptions are evidence that the rule may be miscalibrated. The default response to growing exception pressure is to reassess the guardrail, not automatically blame the developer.

## 19. Legacy and ratchets

Legacy debt MAY be ratcheted when:

- the protected property remains valid;
- the measurement is sufficiently representative of that property;
- new debt can be prevented without harmful remediation incentives;
- improvement can update the baseline automatically or explicitly.

A legacy baseline MUST NOT become permanent immunity.

A ratchet based on a weak proxy inherits the proxy's Goodhart risk; ratcheting does not make a weak metric semantically stronger.

## 20. Architecture evolution

Legitimate evolution follows:

```text
architecture decision
    -> normative contract change
    -> fitness-function change
    -> migration
```

It MUST NOT require an implementation hack solely because an old test froze prior shape.

Tests have lower authority than an intentionally approved successor contract.

## 21. Human-review principles intentionally not fully automated

The following are first-class maintainability principles but are not currently precise enough for universal HARD automation:

| Property | Why it matters | Why not HARD-automated | Supporting signal |
|---|---|---|---|
| Cohesion by reason of change | keeps related policy together | semantic meaning cannot be inferred reliably from LOC | change coupling, concept/ownership diversity |
| Locality of behavior | reduces reasoning/navigation cost | legitimate boundaries require indirection | delegation depth, files traversed |
| Useful abstraction | avoids ceremony | an interface may be essential or useless depending on substitutability/ownership | implementor count, forwarding depth |
| Test scenario locality | preserves readable executable evidence | test size varies strongly by fixture/world complexity | file LOC, support-file hops |
| Semantic non-regression | prevents metric gaming | requires comparison of design meaning | LOC/complexity delta plus review |
| Appropriate module boundary | preserves independent evolvability | domain language and change reasons are contextual | dependency/change coupling |

## 22. Evidence basis and confidence

Important conclusions in this constitution use the following evidence classes:

- **DIRECT REPO EVIDENCE — HIGH:** current ownership docs, dependency tests, layer tests, CI composition, current file-budget implementation.
- **MEASURED REPO DATA — HIGH for available counts; INCOMPLETE for distributions:** the audited exact-head CI records 483 test files and 32 architecture-scope test files, but current CI does not publish full LOC/function-complexity percentile distributions.
- **NORMATIVE ARCHITECTURE — HIGH:** `docs/09-python-module-architecture.md`, `docs/10-module-ownership-map.md`, `docs/14-architecture-fitness-functions.md`, and `docs/testing/repository-governance-contract.md`.
- **TOOL DOCUMENTATION — HIGH:** Ruff documents C901 as function-level McCabe complexity and defaults `max-complexity` to 10 when enabled; Pylint documents module line count as a readability/complexity proxy rather than a semantic invariant.
- **INDUSTRY CONVENTION — MEDIUM:** Linux kernel guidance explicitly relates acceptable function length to complexity and indentation rather than a universal line threshold.
- **EMPIRICAL RESEARCH — MEDIUM:** method-size studies show size can correlate with maintenance effort, but language/method-level results do not justify a universal 120-line Python file invariant.
- **ENGINEERING JUDGMENT — MEDIUM:** navigability/locality diagnostics are valuable, but reliable universal thresholds are not established for this repository.

References:

- Ruff C901: <https://docs.astral.sh/ruff/rules/complex-structure/>
- Ruff McCabe setting: <https://docs.astral.sh/ruff/settings/#lint_mccabe_max-complexity>
- Linux kernel coding style, functions: <https://www.kernel.org/doc/html/latest/process/coding-style.html#functions>
- Pylint `too-many-lines`: <https://pylint.readthedocs.io/en/latest/user_guide/messages/convention/too-many-lines.html>
- SonarSource Cognitive Complexity: <https://www.sonarsource.com/resources/cognitive-complexity/>
- Chowdhury, Uddin, Holmes, *An Empirical Study on Maintainable Method Size in Java*: <https://arxiv.org/abs/2205.01842>

## 23. Acceptance rule

This constitution is acceptable only if the resulting system has sufficient reason **not** to automatically prefer:

```text
smaller files + more wrappers + more hops
```

over:

```text
cohesive responsibilities + moderate size + clear boundaries + short reasoning path
```

The expected answer is **yes** because direct architectural invariants receive stronger authority than file-size proxies, and cohesion/locality/navigability remain explicit review properties rather than casualties of a numeric target.
