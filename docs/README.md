# Request Engine — current documentation

This directory is the system of record for current Request Engine product/domain/architecture design. It is an **index of present authority**, not a chronological feature diary.

Historical release, roadmap and implementation documents may retain the language/status of the checkpoint they recorded. Their age, filename (`v3`, `f1`, `f7`, etc.) or former branch name does not by itself make them current authority.

## 1. Current repository mode

Request Engine is still pre-production and is currently operating under:

1. `architecture/system-optimization-mode.md` — current cohesion/rebaseline mode;
2. `architecture/pre-production-evolution-policy.md` — controlled contract/test evolution policy;
3. `testing/current-guarantees.toml` — canonical semantic guarantee inventory.

Current rule:

```text
freeze guarantees, not accidental repository shape
```

V3 release evidence remains historical provenance. It is not a permanent ceiling on schema, module, test or repository shape. A future production freeze will be established only after the current cohesion/schema review is complete.

## 2. Current architecture map

For present-day ownership and boundaries, start here:

1. `10-module-ownership-map.md` — current business-module ownership;
2. `07-database-access-contract.md` — Python/PostgreSQL ownership and transaction boundary;
3. `09-python-module-architecture.md` — physical Python/module organization;
4. `13-connection-surfaces.md` — mandatory layer/module/DB/provider connection surfaces;
5. `14-architecture-fitness-functions.md` — executable dependency/surface fitness rules;
6. `testing/repository-governance-contract.md` — HARD / CONTROLLED / FLEXIBLE / HISTORICAL classification;
7. `15-api-design-and-usability-standards.md` — current public API design/usability guidance.

The current business-module topology is capability-oriented. Historical feature labels such as F1–F7 describe when contracts/capabilities entered the system, not a requirement to organize current code by roadmap phase.

## 3. Current capability/domain contracts

The documents below remain relevant where their semantics are still accepted. Their paths preserve historical naming; the owning module/contract and current guarantee inventory determine present authority.

### Operational profile / contextual supply

- `v3/15-operational-profile-contextual-supply-contract.md` — Organization/Location operational truth, Resource-at-Location supply, contextual schedule/terms and related booking provenance.
- `adr/0012-contextual-resource-location-supply.md` — durable contextual-supply rationale.

### Discovery

- `v3/24-geospatial-cross-tenant-discovery-contract.md` — authorized cross-tenant publication/search and opaque Booking handoff.
- `adr/0011-cross-tenant-shared-capacity.md` — shared-capacity identity/serialization rationale.

### Live service operations

- `v3/26-live-service-operations-contract.md`
- `v3/28-live-service-operations-integration-amendment.md`

Durable current distinction:

```text
Reservation    = planned commitment/capacity history
QueueEntry     = arrival/wait/call truth
ServiceSession = actual execution truth
```

### Live capacity projection

- `v3/29-live-capacity-projection-contract.md`

Live Capacity is advisory projection over published Booking/Queue/Delivery facts. Scheduled capacity and live intake capacity remain distinct unless a newer accepted contract explicitly replaces that model.

### Operational recovery

- `v3/32-operational-recovery-communications-contract.md`

Operational Recovery composes owner-controlled Booking, Live Capacity and Communications capabilities without becoming their underlying authority.

### Agent operational tooling

- `v3/35-operational-copilot-contract.md`

`operational_copilot` is a historical module name for the bounded typed operational-tool/admission surface. Request Engine owns authoritative lookup/admission/execution boundaries; external agents/applications own conversation/reasoning/tool selection. The historical text parser is not the product definition.

### Front-desk / communications / identity / onboarding contracts

Later contracts include:

- `v3/36-front-desk-operations-contract.md`
- `v3/38-s0b-party-registry-contract.md`
- `v3/43-same-day-triage.md`
- `v3/44-business-onboarding-bootstrap-contract.md`

These documents define accepted capability semantics where implemented. **Do not infer active branch, completion, deployment or current roadmap priority from the F/S label alone.** When implementation status matters, verify the actual repository/current-product evidence.

Implementation plans/inventories adjacent to these contracts are useful provenance and review evidence but are subordinate to current normative contracts and present repository state.

## 4. Baseline V3 design sources

These remain important design/provenance sources where a current contract still relies on them:

- `11-capability-first-v3.md`
- `v3/01-capability-contracts.md`
- `v3/02-pre-sql-contract.md`

They do not freeze current schema/repository shape. Newer accepted capability contracts and `architecture/system-optimization-mode.md` may supersede structural assumptions while preserving equal-or-stronger semantic guarantees.

V2 documents such as `00-product-definition.md`, `01-architecture-v2.md` and `02-pre-sql-domain-contract.md` are historical/source material unless a current document explicitly adopts a particular idea.

## 5. Testing and guarantee governance

Canonical test/evidence entry points:

- `testing/current-guarantees.toml` — normative current semantic guarantee inventory;
- `testing/README.md` — current test architecture and CI evidence model;
- `testing/repository-governance-contract.md` — repository/test/instruction rigidity classification;
- `testing/evidence-authoring-guide.md` — falsifiable proof workflow;
- `testing/current-proof-map.toml` — non-normative representative-proof migration map;
- `testing/test-architecture-migration.md` — test-taxonomy/disposition provenance.

A green general CI run is not by itself proof of every product capability. Exact-head evidence must still satisfy the applicable current guarantees and capability contract.

Current test paths may still contain `v3_*`, `f1_*`, `f2_*`, etc. Those names are historical provenance and may be consolidated during system optimization without changing a guarantee.

## 6. Engineering quality

Engineering-quality entry points:

- `engineering-quality/README.md`
- `engineering-quality/executable-fitness-function-specification.md`
- `engineering-quality/semantic-review-protocol.md`
- `engineering-quality/agent-semantic-review-playbook.md`
- `engineering-quality/local-publish-certification.md`
- `engineering-quality/guardrail-decision-record.md`

File LOC, C901, navigation/file-count observations and module fan-in/fan-out are heuristic review evidence. They are not automatic architecture verdicts. The retired hard file-size/mega-file experiments must not be presented as current merge blockers unless reintroduced through the documented HARD-gate approval process.

## 7. PostgreSQL executable truth

Executable schema evolution lives under `migrations/`, not in this documentation index.

Current authority:

```text
migrations/versions/     current Alembic line
migrations/README.md     current schema-evolution/rebaseline policy
migrations/AGENTS.md     schema-working rules
```

Do **not** copy a particular revision such as `0006` or `0034` into this index as timeless “current head”. The current head is discovered from the actual repository Alembic graph; CI requires exactly one head and upgrades a clean PostgreSQL 18 database to that head.

Historical SQL/provenance surfaces such as:

```text
migrations/sql/v3_candidate/
migrations/sql/design_chain/
migrations/f2_steps/
```

are not current schema authority merely because they remain in the tree. Their retention/archival value will be dispositioned during the historical/release archaeology phase.

Any future schema rebaseline is a dedicated controlled operation after the complete current PostgreSQL audit, governed by `architecture/system-optimization-mode.md` and `migrations/README.md`.

## 8. Release/historical provenance

`release/`, legacy transition documents and historical SQL/release artifacts answer questions such as:

```text
what did we prove then?
what design decision existed at that checkpoint?
```

They do not automatically answer:

```text
what must current Request Engine look like now?
```

The former frozen-V3 compatibility runner/historical test lane has been retired from active current CI during system optimization. Do not reintroduce it from an old document without a concrete present compatibility/provenance need and an explicit governance decision.

`legacy/**` is historical and non-authoritative unless a task explicitly asks to inspect it.

## 9. Documentation precedence

For a current change, use this precedence model:

```text
system-optimization mode / current guarantee inventory
        ↓
owning current capability/domain contract
        ↓
current ownership + connection/database contracts
        ↓
repository/test governance + executable fitness functions
        ↓
implementation plans / inventories / handoffs
        ↓
historical release / transition / V2 material
```

A newer accepted capability contract may explicitly supersede an older structural rule. It must not silently weaken HARD guarantees.

When two **current** documents disagree, treat that as a repository defect: identify the semantic owner, reconcile the contradiction and update current indexes/tests in the same coherent change.

## 10. Handoff documentation

`handoff/` contains operational snapshots intended to help another engineer/agent resume work. Handoffs are not competing specifications and may describe traps or status that were true when written.

During system optimization:

- current contracts/policies have precedence over handoff status text;
- do not preserve a retired freeze, branch name, test ratchet or migration checkpoint merely because a handoff mentions it;
- stale handoff statements should be corrected or archived when they would misdirect current work.

## 11. Documentation policy

Repository documentation is the source of truth. Agent instruction files are concise routers/guardrails.

- Durable domain/capability rules belong in the owning current contract.
- Durable rationale belongs in `adr/`.
- Testing/repository governance belongs in `testing/`.
- Engineering-quality policy belongs in `engineering-quality/`.
- Executable SQL/schema evolution belongs in `migrations/`.
- Historical release evidence may preserve historical wording.
- Current indexes, READMEs and instructions must describe the present system and must not present an obsolete branch, release candidate, frozen CI lane or migration checkpoint as current authority.
