# Documentation agent rules

Applies to `docs/**`; `docs/legacy/AGENTS.md` is stricter for the historical archive.

## Current authority

- `architecture/system-optimization-mode.md` is the current repository-wide cohesion/rebaseline policy while Request Engine remains pre-production. Current indexes, READMEs and agent instructions must not contradict it.
- `testing/current-guarantees.toml` inventories current semantic guarantees. Historical V2/V3/F1-F7 names, branches, migration checkpoints and release lanes are not current authority merely because older documents mention them.
- `docs/README.md` is the current documentation index and precedence map. Keep it about the present system; do not turn it into a chronological feature diary.
- `architecture/docker-e2e-ci-plan.md` is the canonical architecture/execution contract for the reusable Docker system/E2E CI platform. Individual journeys such as F-01 are consumers of that platform and must not silently redefine its topology or runner model.

## Document ownership

- Current capability semantics belong to the owning indexed capability/domain contract; the historical `v3/` path/name does not itself freeze V3 repository shape.
- `11-capability-first-v3.md` and `v3/01-capability-contracts.md` remain important baseline design sources where their guarantees are still current, but newer accepted contracts and the optimization-mode policy may supersede structural assumptions explicitly.
- `00-product-definition.md`, `01-architecture-v2.md` and `02-pre-sql-domain-contract.md` remain V2 source material; do not silently copy retired V2 concepts into current design.
- Python/PostgreSQL ownership belongs in `07-database-access-contract.md` unless a newer accepted contract explicitly supersedes a concept.
- Python physical/module architecture belongs in `09-python-module-architecture.md`.
- Module ownership belongs in `10-module-ownership-map.md`.
- Connection surfaces belong in `13-connection-surfaces.md`.
- Executable architecture dependency rules belong in `14-architecture-fitness-functions.md`.
- HTTP/OpenAPI usability/design rules belong in `15-api-design-and-usability-standards.md`.
- Owner/capability/operation/tool-projection rules for UX, integrations and agents belong in `16-canonical-operation-and-tool-projection-pattern.md`.
- Reusable system/E2E deployment, runner isolation, suite registry, suite selection, fresh-world policy, fault-injection orchestration and evidence boundaries belong in `architecture/docker-e2e-ci-plan.md`.
- Pre-production contract/test evolution belongs in `architecture/pre-production-evolution-policy.md`; system-optimization authority for the current phase belongs in `architecture/system-optimization-mode.md`.
- Repository/test/DTO/naming/LLM rigidity-versus-flexibility rules belong in `testing/repository-governance-contract.md`.
- Current guarantee inventory and representative proof mapping belong under `testing/`.
- Schema-evolution/current executable migration truth belongs under `migrations/`, especially `migrations/README.md`; do not copy a fixed Alembic head into docs as timeless current truth.
- Hard-to-reverse rationale belongs in `adr/`.
- Release provenance belongs under `release/` or Git history/releases/tags and is HISTORICAL unless explicitly reactivated by a current compatibility obligation.

## Reusable E2E documentation discipline

When documenting a new system/E2E suite, distinguish three layers:

```text
product/capability contract   -> what behavior/guarantee the journey must prove
E2E platform contract         -> how reusable deployment/runner/orchestration works
suite definition              -> selector, required profiles, checkpoints and evidence for this journey
```

Do not copy feature-specific steps into the platform contract unless they create a reusable platform requirement. Conversely, do not create a private feature-specific Compose/workflow architecture when the reusable platform can execute the suite.

Ordinary new suites should update the suite registry/nearby testing documentation and owning guarantee/proof maps as appropriate. Update `architecture/docker-e2e-ci-plan.md` only when changing the reusable platform contract itself: topology, runner isolation, registry schema, fresh-world semantics, selection policy, evidence contract, fault-injection protocol, secret/state handling or supported exception model.

`all` must remain documented as independent fresh-world executions by default, not as one shared mutable business database. Cost optimizations that share state require an explicit documented exception and proof of independence.

Specialized browser/load/contract runners are allowed when the evidence technology genuinely differs. Documentation must name why the generic black-box runner is insufficient and which isolation guarantees remain applicable.

Never document a green Docker E2E result as production certification for properties outside its evidence boundary, including real external TLS/ingress, production Vault HA/policies, real deliverability, production-shaped backup/restore fencing, human break-glass, RPO/RTO or SLOs.

## API / tool documentation gate

For any new or changed machine-facing operation, docs must preserve the distinctions in docs 15/16:

```text
business owner
capability authorization policy
OpenAPI operationId
optional agent-tool name/audiences
```

Do not document those as interchangeable identifiers.

Do not introduce a second hand-maintained operation/tool registry that copies `CapabilityDefinition` policy. Agent/MCP surfaces project existing owner operations; they do not become business owners or bypass owner authorization.

Public/operator/admin are discovery/trust profiles, not sufficient authorization by themselves. Documentation must not imply that hiding a tool or placing it on a private route grants or denies business authority.

When documenting a new agent tool, identify the owner operation and capability it delegates to. If that delegation cannot be stated clearly, the tool design is incomplete.

## Integrity rules

- Avoid copying the same normative rule into multiple documents; reference the owner document.
- When a HARD or CONTROLLED rule changes, update its canonical owner first, then indexes/agent maps/tests in the same coherent change.
- When a rule changes, search for stale contradictory **current** examples elsewhere.
- Historical documents may preserve historical wording. Current READMEs/maps/instructions must not present historical branches, release candidates, frozen compatibility runners, migration checkpoints or feature status as current unless verified.
- A filename/path such as `v3/*`, `f1_*` or `f7_*` is provenance/naming, not proof of present authority or implementation status.
- Do not describe a feature as active, complete, shipped or pending merely from a roadmap label. Use verified repository/product evidence when status matters.
- Executable SQL belongs under `migrations/`, not `docs/`.
- Never modify `legacy/**` unless explicitly requested.
