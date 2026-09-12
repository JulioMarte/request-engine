# Request Engine — current documentation

This directory is the system of record for current Request Engine product/domain/architecture design. It is an **index of present authority**, not a chronological feature diary.

Historical release, roadmap and implementation documents may retain the language/status of the checkpoint they recorded. Their age, filename (`v3`, `f1`, `f7`, etc.) or former branch name does not by itself make them current authority.

## 1. Evolution authority

Request Engine follows a permanent controlled-evolution model:

1. `architecture/continuous-evolution-policy.md` — **permanent evolution contract**: immutable history, evolvable future; migrations, compatibility, deprecation, rollout and production transition;
2. `architecture/system-optimization-mode.md` — temporary current pre-production cohesion/optimization mode;
3. `architecture/pre-production-evolution-policy.md` — additional breaking-change freedom while no customer-owned production data or external compatibility promise exists;
4. `testing/current-guarantees.toml` — canonical semantic guarantee inventory.

The two governing phrases are:

```text
immutable history, evolvable future
freeze guarantees, not accidental repository shape
```

There is no planned blanket architecture freeze. A production release may make particular history, data obligations and published compatibility commitments immutable; current architecture continues to evolve through controlled, migration-safe changes.

## 2. Current architecture map

Native initial provisioning authority is specified in
`architecture/initial-controller-policy.md`; executed validation and remaining
production gaps are tracked in `architecture/auth-implementation-status.md`.
Current agent lifecycle/revision inspection and its explicit read authority are
specified in `architecture/agent-governance-inspection.md`.

For present-day ownership and boundaries, start here:

1. `10-module-ownership-map.md` — current business-module ownership;
2. `07-database-access-contract.md` — Python/PostgreSQL ownership and transaction boundary;
3. `09-python-module-architecture.md` — physical Python/module organization;
4. `13-connection-surfaces.md` — mandatory layer/module/DB/provider connection surfaces;
5. `14-architecture-fitness-functions.md` — executable dependency/surface fitness rules;
6. `testing/repository-governance-contract.md` — HARD / CONTROLLED / FLEXIBLE / HISTORICAL classification;
7. `15-api-design-and-usability-standards.md` — current HTTP/OpenAPI house standard;
8. `16-canonical-operation-and-tool-projection-pattern.md` — normative owner/capability/operation/tool projection pattern for UX, integrations and agents.

Historical feature labels such as F1–F7 describe when capabilities entered the system; they do not define current package topology or create permanent compatibility obligations.

## 3. Current API / agent-tool authority

For any new machine-facing operation, read docs 15 and 16 together.

The governing shape is:

```text
business owner
    -> capability policy
    -> typed semantic operation
    -> canonical HTTP/OpenAPI
    -> optional authorized tool/MCP projection
```

Do not create a second business implementation for agents. `CapabilityDefinition` remains authorization-policy authority; OpenAPI `operationId` identifies one HTTP operation; an optional tool name identifies an agent-facing projection. These identities are related but not interchangeable.

The historical `operational_copilot` package is not a separate source of business truth. Its structured tools are migration input toward the generic authorized operation/tool gateway described by doc 16.

Identity/authentication and deployment references:

- `architecture/identity-provider-and-staff-provisioning-plan.md` — providerless trust root, staff lifecycle and required acceptance journeys;
- `architecture/principal-agent-and-provisioning-authority-model.md` — Principal planes, workload authority and the amended implementation slice order;
- `architecture/http-runtime-deployment.md` — native-first and separate private provisioning ASGI factories, explicit configuration, least-privilege startup and readiness limits.
- `architecture/auth-implementation-status.md` — dated local verification evidence and remaining identity-plan acceptance gaps; not a production certification.

## 4. Current capability/domain contracts

Historical paths may contain current semantic contracts. Authority comes from the owning module, current guarantee inventory and accepted contract status — not from the path name.

Important current contract families include:

- operational profile / contextual supply — `v3/15-operational-profile-contextual-supply-contract.md`;
- discovery — `v3/24-geospatial-cross-tenant-discovery-contract.md`;
- live service operations — `v3/26-live-service-operations-contract.md` and its accepted amendments;
- live capacity — `v3/29-live-capacity-projection-contract.md`;
- operational recovery — `v3/32-operational-recovery-communications-contract.md`;
- historical operational agent tooling contract — `v3/35-operational-copilot-contract.md`, now interpreted through current docs 15/16 and the ownership map;
- front desk / communications / identity / onboarding — later accepted contracts under `v3/` where their current owner/guarantee semantics remain adopted.

Durable business distinctions such as Reservation versus QueueEntry versus ServiceSession remain current where adopted by the guarantee/owner contracts. Historical structural descriptions do not freeze implementation shape.

## 5. Testing and guarantee governance

Canonical evidence entry points:

- `testing/current-guarantees.toml` — current semantic guarantees;
- `testing/README.md` — current test architecture and CI evidence model;
- `testing/repository-governance-contract.md` — repository/test rigidity classification;
- `testing/evidence-authoring-guide.md` — falsifiable proof workflow;
- `testing/current-proof-map.toml` — representative proof mapping;
- `testing/test-architecture-migration.md` — test-taxonomy/disposition provenance.

Architecture tests should strongly enforce HARD properties, detect CONTROLLED drift and avoid freezing FLEXIBLE implementation details. Historical exact snapshots/fingerprints belong to historical evidence, not current-head ceilings.

A useful rule for every new durable gate is:

```text
If a legitimate future feature fails this assertion, what semantic/compatibility risk must that feature prove before the assertion may evolve?
```

If there is no meaningful answer beyond “the list/file/count changed”, the gate is probably freezing implementation shape and should not be HARD.

## 6. Engineering quality

Engineering-quality entry points:

- `engineering-quality/README.md`;
- `engineering-quality/executable-fitness-function-specification.md`;
- `engineering-quality/semantic-review-protocol.md`;
- `engineering-quality/agent-semantic-review-playbook.md`;
- `engineering-quality/local-publish-certification.md`;
- `engineering-quality/guardrail-decision-record.md`.

LOC, C901, file counts and fan-in/fan-out are heuristic review signals. They are not permanent merge-blocking architecture laws without an explicit HARD-gate proof obligation and normative approval.

## 7. PostgreSQL executable truth

Executable schema evolution lives under `migrations/`.

Current layout:

```text
migrations/versions/          active Alembic lineage
migrations/baseline/          immutable accepted 0001_initial payload
migrations/sql/design_chain/  retained historical V2 evidence still exercised by CI
```

`0001_initial` is immutable migration history, **not the maximum schema Request Engine is allowed to have**. Ordinary product evolution appends `0002+` from the single current Alembic head.

Never copy a current migration number into general documentation as a timeless head. CI discovers the actual graph, requires one current head and proves clean `alembic upgrade head`.

The old V3 Base85 payload, V3 candidate SQL, feature-step migration helpers and pre-rebaseline revision chain have been removed from current executable authority. Their provenance remains in Git/history. Do not reintroduce them merely because an old handoff or release document mentions them.

For database work read:

1. `architecture/continuous-evolution-policy.md`;
2. `migrations/README.md`;
3. `migrations/AGENTS.md`;
4. `07-database-access-contract.md`;
5. the affected capability contract and guarantees.

## 8. Compatibility and production transition

Compatibility burden attaches to real consumers and data, not to every old repository shape.

Before production/customer commitments, controlled breaking changes may be accepted with explicit contract/test disposition.

When customer-owned production data or an independently deployed/external supported consumer exists, the compatibility trigger has fired. From then on:

- accepted/applied migration history remains immutable;
- schema still evolves through appended migrations;
- use expand → migrate → contract when old/new representations must coexist;
- destructive changes require explicit data/consumer migration and recovery analysis;
- published surfaces require observable deprecation/removal criteria;
- high-risk production changes require appropriate rollout/mitigation evidence;
- rebaseline is no longer a repository-cleanup technique.

See `architecture/continuous-evolution-policy.md` for the normative details.

## 9. Historical provenance

Historical release and transition material answers:

```text
what did we prove then?
what decision existed at that checkpoint?
```

It does not automatically answer:

```text
what must current Request Engine look like now?
```

`legacy/**`, former V2/V3 release evidence, old handoffs and removed migration machinery are non-authoritative unless a current contract explicitly adopts a specific guarantee or pattern.

## 10. Documentation precedence

For a current change use this precedence model:

```text
continuous-evolution policy + current guarantee inventory
        ↓
current phase policy (for example system-optimization mode)
        ↓
owning current capability/domain contract
        ↓
current ownership + connection/database/API-operation contracts
        ↓
repository/test governance + executable fitness functions
        ↓
implementation plans / inventories / handoffs
        ↓
historical release / transition / V2 material
```

No phase policy may silently weaken a HARD guarantee. No historical structural statement may silently become a permanent freeze.

When two current normative documents disagree, treat that as a repository defect: identify the semantic owner, reconcile the contradiction and update current indexes/tests in the same coherent change.

## 11. Documentation policy

Repository documentation is the source of truth. Agent instruction files are operational routers/guardrails.

- durable domain/capability rules belong in the owning current contract;
- durable evolutionary rules belong under `architecture/`;
- durable API/operation/tool projection rules belong in docs 15/16;
- durable rationale belongs in `adr/`;
- testing/repository governance belongs in `testing/`;
- engineering-quality policy belongs in `engineering-quality/`;
- executable SQL/schema evolution belongs in `migrations/`;
- historical release evidence may preserve historical wording;
- current indexes, READMEs and instructions must describe the present system.

A compatibility shim, deprecated contract, feature flag or historical proof retained for current operation must have a real reason to exist. Where applicable it should have an owner and retirement criterion so temporary protection does not become the next accidental freeze.
