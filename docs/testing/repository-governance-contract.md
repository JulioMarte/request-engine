# Request Engine — Repository, Test, and Agent Governance Contract

Status: **normative current repository-governance contract**.

This document defines which repository/test conventions are intentionally rigid, which may evolve through an explicit architecture decision, and which are implementation details that tests should not freeze.

The goal is not maximum rigidity or maximum flexibility. The goal is **rigidity at semantic boundaries and flexibility inside those boundaries**.

## 1. Change-authority classes

Every structural assertion should belong to one of four classes.

### A. HARD — invariant or semantic boundary

These fail closed by default. A normal feature/refactor must not weaken them merely because another implementation is convenient.

Examples:

- tenant isolation, authority, atomicity, idempotency, capacity ownership, provenance, least privilege and bounded failure semantics;
- module-first ownership and acyclic business-module dependencies;
- cross-module imports through published `contracts` surfaces only;
- `domain` remains framework/persistence/transport independent;
- `application` remains independent of concrete DB/provider/HTTP adapters;
- module `contracts` remain framework-free and do not re-export internal domain/application/adapter/API objects;
- persistence mappings/results are not HTTP DTOs or cross-module contracts;
- API/transport DTOs are distinct from domain, application, contract and persistence types;
- authoritative mutations are semantic Commands, not generic CRUD/service-manager abstractions;
- repository documentation is the source of truth; LLM adapter files route to the same repository/local `AGENTS.md` contracts;
- the serialized `development` integration workflow and exact-head CI requirement.

Changing one of these requires an explicit newer normative contract with equal-or-stronger safety, test disposition, documentation update and exact-head proof. It is never a mechanical allowlist edit.

### B. CONTROLLED — accepted architecture/product shape

These are rigid for ordinary work but may change when a real capability demonstrates that the current design is insufficient.

Examples:

- the current set of business modules;
- approved synchronous module dependency edges;
- capability names and public/internal contract versions;
- public HTTP/tool shapes;
- transaction/lock topology;
- current migration strategy;
- ownership of a capability by a specific module.

Tests should detect unreviewed drift, but they should protect the **decision process and resulting semantics**, not assume the old list can never change.

### C. FLEXIBLE — implementation shape

These should normally be free to change without architecture-policy edits as long as A/B contracts remain true.

Examples:

- function versus small handler object;
- private helper names;
- exact test filenames and test counts;
- internal file splits inside the owning layer;
- fixture organization;
- which representative test path proves a guarantee;
- additive private refactors that do not alter supported boundaries.

Do not create exact snapshots for these details merely because they are easy to assert.

### D. HISTORICAL — pinned release provenance

Historical release artifacts answer `what exactly did we prove then?`. They may intentionally pin exact commits, files, manifests and schemas, but they must resolve those assertions against the historical release/tree rather than requiring current head to retain historical shape.

## 2. DTO and type-boundary rules

The following distinctions are semantic and therefore HARD:

```text
HTTP request DTO      != application Command
HTTP response View    != domain/contract entity
cross-module contract != domain entity
cross-module contract != persistence row
persistence row       != HTTP DTO
provider SDK type     != domain/application contract
```

Current transport naming convention:

- top-level HTTP JSON request bodies use a descriptive `*Body` class;
- HTTP response/read projections use a descriptive `*View` class;
- transport-only query/path helper models, if introduced, use a transport-explicit suffix such as `*Params` rather than masquerading as a domain entity;
- nested request components may use a descriptive transport-explicit suffix such as `*InputModel`; they are not required to masquerade as top-level `*Body` objects merely to satisfy a filename/class snapshot;
- module cross-boundary business values live under `contracts` and use business language rather than `Body`, `View`, `Row`, `ORM`, `Schema`, or provider-specific names.

The spelling itself is not the invariant. The invariant is that transport role remains visible and cannot be confused with domain/application/contracts/persistence. Changing the accepted transport naming convention is CONTROLLED and must update this contract and its fitness function together.

Pydantic is a transport/configuration technology. Business-module `domain`, `application`, and cross-module `contracts` must not depend on it. Bootstrap/runtime configuration may use Pydantic where appropriate because that is a technical boundary, not a business DTO boundary.

## 3. Naming and abstraction rules

The repository intentionally rejects generic business buckets that erase ownership.

Do not introduce module-level business abstractions named only for implementation mechanics such as:

```text
services.py
managers.py
helpers.py
utils.py
common.py
```

A repository/adaptor name must express the capability or persistence role it owns. A generic `repositories.py` or shared business `models.py` is not an escape hatch from deciding ownership. `api/models.py` is permitted because its ownership is explicitly the module's transport DTO boundary; persistence model files remain adapter-local and must never become public contracts.

Semantic operation names should expose intent (`BookAppointment`, `JoinQueue`, `RecordDeliveryResult`) instead of table mutation (`UpdateReservation`, `SetQueueStatus`) unless the latter is genuinely the business capability.

## 4. LLM instruction integrity

Repository instructions are part of the engineering control plane.

Canonical model:

```text
repository docs = source of truth
AGENTS.md       = concise operational map/guardrails
CLAUDE.md       = adapter to AGENTS.md
GEMINI.md       = adapter to AGENTS.md
nearest local instruction file adds stricter path-specific rules
```

Important boundaries (`docs`, `migrations`, `src/request_engine/modules`, `tests`) must provide local `AGENTS.md` instructions and matching Claude/Gemini adapters where those tools are supported. Adapter files must route to the local/root `AGENTS.md`; they must not become independent architecture manuals with contradictory rules.

A durable architecture/test rule belongs in canonical documentation first. Agent instructions may summarize it and link to it. If an LLM needs a rule to work safely and repeatedly, that rule should be discoverable from the root instruction map and, when path-sensitive, from the nearest local instruction file.

Historical/current-document tests must distinguish **authority direction** from **mere mention**. A current instruction file may mention an obsolete document precisely to warn an LLM not to use it; fitness should reject stale authority, not the explanatory string itself.

## 5. Documentation integrity

Documentation changes are part of correctness when they alter a durable contract.

For a HARD or CONTROLLED change:

1. update the canonical owner document;
2. update any ADR when the rationale is hard to reverse;
3. update `docs/README.md` precedence/indexing when authority changes;
4. update relevant `AGENTS.md` maps when an LLM must discover the new rule;
5. search for stale contradictory current examples;
6. adapt/replace architecture/contract tests in the same coherent change.

Historical documents may retain historical wording. Current maps/READMEs/instructions may not rely on historical docs as current authority.

## 6. Test design implications

Architecture tests should strongly enforce class A, detect class B drift, avoid freezing class C, and pin class D only to historical trees/releases.

A useful review question for every new architecture test is:

```text
If this assertion fails because of a legitimate future feature, what exactly must that feature prove before changing the assertion?
```

If the answer is "nothing; the filename/list simply changed", the assertion probably belongs to FLEXIBLE implementation shape and should be rewritten semantically.

If the answer is "the change crosses a trust/type/ownership/transaction boundary", the assertion belongs to HARD or CONTROLLED governance and should fail loudly with actionable guidance.

## 7. Required review for repository-governance changes

Any change to this contract, `AGENTS.md`, module/layer boundary rules, DTO/type-boundary conventions, or architecture fitness policy must identify:

```text
classification: HARD / CONTROLLED / FLEXIBLE / HISTORICAL
protected risk
authoritative document
fitness/contract proof affected
LLM instruction impact
compatibility impact (if any)
```

This prevents two opposite failure modes: accidental architecture erosion disguised as "flexibility", and accidental product paralysis disguised as "architecture enforcement".
