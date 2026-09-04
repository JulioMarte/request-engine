# Request Engine — agent map

These instructions apply repository-wide. A nearer `AGENTS.md` may add path-specific rules but must not contradict current repository policy.

## Reporting discipline — mandatory

When reporting changes:

1. explain what changed in production/system terms;
2. state explicitly what was NOT changed and any pre-existing issues discovered;
3. surface decisions made and pending decisions clearly;
4. never report a check as passed unless it actually ran against the intended environment.

## Current repository mode

Request Engine is pre-production and currently operating under the explicit cohesion/rebaseline policy in:

`docs/architecture/system-optimization-mode.md`

The current objective is to converge the repository on one coherent present-day architecture before the next production freeze.

During this phase, repository/schema/module/test shape is CONTROLLED but mutable when an explicit change improves the current system. Semantic guarantees are not casually mutable. `docs/testing/current-guarantees.toml` is the canonical guarantee inventory.

Do not preserve V2/V3/F1-F7 release archaeology merely because it once existed. Do not remove it merely because it looks old either: classify it by current guarantee, compatibility and provenance value first.

## Branch workflow — mandatory

`development` is the canonical integration branch. `main` is release-only. Request Engine uses one serialized ordinary development integration lane.

For ordinary feature, fix, refactor, test, documentation, release-proof or agent work:

1. resolve current `origin/development`;
2. do not maintain a second merge-ready sibling ordinary workstream;
3. create/rebuild the work branch from current `development`;
4. set `.github/development-integration-lane` to exactly the work branch name;
5. open the PR against `development`;
6. finish the coherent change on that branch;
7. if `development` changes, reconcile the branch and reclaim the lane;
8. require exact-head CI/evidence before merge;
9. merge into `development` and delete the branch;
10. then start the next ordinary branch from the new integrated head.

`tmp/*` branches are scratch/reconciliation space only and must not become ordinary PR heads.

The only normal PR targeting `main` is `development -> main` release promotion.

`tests/architecture/test_branch_workflow_contract.py` enforces this topology. Do not weaken it to bypass a lane mismatch.

## Local publish certification — mandatory for local agents

Local commits are checkpoints and MAY be incomplete or red. Do not install a mandatory pre-commit quality gate.

Before local `git push`, use the managed pre-push certification described in `docs/engineering-quality/local-publish-certification.md`.

- install/refresh with `uv run python scripts/dev/install_git_hooks.py`;
- the certificate applies to the exact commit SHA, base SHA and toolchain it records;
- never use `git push --no-verify` to bypass publication certification;
- local certification is publication permission, not merge evidence;
- local certification MUST NOT cause remote CI lanes to be skipped;
- GitHub exact-head CI remains authoritative.

Agents working directly through GitHub do not have a local certificate and must rely on full PR CI/evidence.

## Start here

Read only the canonical material needed for the change, in this order where relevant:

1. `docs/architecture/system-optimization-mode.md` — current cohesion/rebaseline mode;
2. `docs/README.md` — documentation map and current contracts;
3. `docs/testing/current-guarantees.toml` — current semantic guarantees;
4. `docs/10-module-ownership-map.md` — business ownership;
5. owning `src/request_engine/modules/<module>/README.md`;
6. current capability/domain contract affected by the change;
7. `docs/07-database-access-contract.md` — Python/PostgreSQL ownership;
8. `docs/09-python-module-architecture.md` — Python layout/layers;
9. `docs/13-connection-surfaces.md` — layer/module/DB/provider boundaries;
10. `docs/14-architecture-fitness-functions.md`;
11. `docs/testing/repository-governance-contract.md`;
12. `docs/testing/evidence-authoring-guide.md` when changing tests;
13. `migrations/README.md` and `migrations/AGENTS.md` when touching schema;
14. `docs/adr/README.md` for hard-to-reverse design decisions;
15. `docs/15-api-design-and-usability-standards.md` for public API changes.

Historical V2/V3/F1-F7 plans, release evidence and transition documents are sources of provenance and proven patterns, not automatic current authority. A current accepted capability contract may explicitly retain one of their guarantees.

`docs/legacy/**` is historical and non-authoritative.

## Non-negotiable architecture

- Modular monolith: module-first, capability-local, layer-conscious, explicit connection surfaces.
- Cross-module imports use the target module's supported `contracts` surface; never another module's `domain`, `application`, `adapters` or `api` internals.
- Business HTTP routers/models/error mappings belong to the owning module's `api` package. `entrypoints/http` is composition/trust-boundary code, not a parallel business taxonomy.
- HTTP/provider DTOs, application Command/Query types, domain values, cross-module contracts and persistence mappings remain distinct type boundaries.
- Business `domain`, `application` and `contracts` remain Pydantic-free.
- Entrypoints/bootstrap compose modules through published surfaces; business code must not use bootstrap as a service locator.
- `platform` contains technical cross-cutting mechanics only, never displaced business policy.
- Domain code does not import FastAPI, SQLAlchemy, provider SDKs or runtime/bootstrap configuration.
- Public operations are explicit Query, semantic Command, durable business Request or ScheduledAction; do not collapse them behind a generic workflow/service abstraction.
- Authoritative state changes are semantic commands, not generic CRUD.
- PostgreSQL owns structural truth, locks, atomic consistency backstops and durable facts. Python owns command semantics, policy orchestration and transaction framing.
- One authoritative command normally uses one Session/AsyncSession and one explicit DB transaction.
- Never perform external network I/O while holding authoritative DB locks.
- n8n/providers are adapters/extensions, not owners of business authority.
- `request_read.*` is a read contract. `request_cmd.*` contains narrow consistency/worker/idempotency primitives, not workflow-sized stored procedures.

`payments` and `dispatch` remain deferred/incubating until a concrete accepted capability gives them real ownership.

## Repository governance classification

When a rule blocks a legitimate change, classify what it protects before editing it:

```text
HARD        semantic/invariant boundary; fail closed by default
CONTROLLED  accepted architecture/product shape; explicit evolution required
FLEXIBLE    private implementation detail; do not freeze gratuitously
HISTORICAL  release/design provenance; evaluate against historical context
```

System optimization expands what may be changed under CONTROLLED/FLEXIBLE. It does not convert HARD guarantees into optional behavior.

## Connection-surface design gate

Before adding or changing a capability/module/provider connection, identify:

```text
Business owner
Capability
Inbound caller/contract
Authentication/authorization boundary
Application Command/Query
Transaction/idempotency boundary
Domain invariants
Database surface
Cross-module contract surface
Provider/event/scheduled surface
Failure/retry/reconciliation semantics
```

For PostgreSQL writes additionally identify `READ / PLAN / LOCK / VALIDATE / WRITE / EMIT`, lock roots/order, tenant context, constraints relied upon and concurrent-loser semantics.

For provider surfaces identify timeout, idempotency, retryability, ambiguous outcomes and reconciliation. Never blind-retry an externally ambiguous operation.

## Architecture fitness failures

Architecture tests are executable design constraints, not style suggestions.

If one fails:

1. identify the boundary/dependency edge;
2. verify ownership and whether the connection must be synchronous;
3. use an existing supported contract/port when available;
4. design a new explicit surface only when genuinely required;
5. update current architecture docs/policy coherently when accepting a new edge.

Do not make CI green by automatically widening allowlists, moving business code into platform/common/shared, re-exporting internals through contracts, suppressing the test, or replacing required atomicity with events for aesthetics.

## Maintainability review candidates

File LOC, Ruff C901, file count, navigation observations, fan-in and fan-out are heuristic sensors, not architecture verdicts.

```text
effective file LOC > 120  -> QR-FSIZE-001 REVIEW_CANDIDATE
McCabe > 10                -> QR-CPLX-001 REVIEW_CANDIDATE
new outbound module edge   -> QR-COUPLING-001 REVIEW_CANDIDATE
```

These signals are non-blocking. There is no hard 120-line architecture ceiling.

Every `REVIEW_CANDIDATE` must be reviewed through `docs/engineering-quality/agent-semantic-review-playbook.md` and `docs/engineering-quality/semantic-review-protocol.md`. `HEALTHY_AS_IS` is a valid semantic disposition.

Do not split/extract solely to lower a metric. Review responsibility, real reasoning complexity, side effects, locality, ownership, abstraction value and testability.

Do not game sensors with forwarding wrappers, one-function modules, service locators, runtime imports, re-export facades, duplicate logic or generic utility buckets.

A deterministic `INVARIANT_FAILURE` cannot be waived by semantic review. If code changes after a review candidate, rerun deterministic architecture, lint/type and relevant behavior proofs.

## Test evidence discipline

A green test is not automatically evidence. Before adding/changing durable proof, identify:

```text
protected guarantee/risk
plausible defect that must make the test fail
real execution boundary
valid business-plausible preconditions
independent oracle
important authoritative state/absence of side effects
canonical CI lane
```

Do not seed the result the operation is supposed to create or compute the expected answer using the same production helper.

When PostgreSQL semantics are part of the claim, use real PostgreSQL 18. Concurrency evidence uses independent transactions/connections and deterministic synchronization, not one transaction or timing-only sleeps.

Current test paths/names such as `v3_*`, `f1_*`, `f2_*` are historical naming, not a requirement that current architecture keep those shapes.

## Product-language discipline

Preserve current distinctions unless an explicit newer contract replaces them:

- Request = durable new business demand requiring later processing; ordinary mutations are Commands by default.
- Reservation = planned commitment; QueueEntry = waiting/calling; ServiceSession = actual execution.
- Resource remains the current capacity serialization root and CapacityClaim the Hold/Reservation consumption truth unless a stronger explicitly designed authority model replaces them.
- ServiceQueue is current service flow; Waitlist is future-capacity interest.
- Reservation confirmation and attendance confirmation remain distinct.
- Communications owns transactional communication intent/delivery semantics; providers are adapters.
- Discovery, Live Capacity, Operational Recovery and agent tooling may compose owner capabilities but do not gain shadow authority over owner facts.
- Prefer stable capabilities such as `appointments.book`, `queue.join`, `waitlist.accept_offer`, `requests.submit` over table-shaped endpoints/tools.

Historical V3 language is evidence, not a permanent naming constraint.

## File/abstraction discipline

Prefer the smallest structure that keeps ownership and reasoning locality obvious. Do not create ceremonial empty Clean Architecture trees.

Avoid generic dumping grounds such as `utils.py`, `helpers.py`, `common.py`, `services.py`, `managers.py`, global generic repositories or shared business models.

Do not infer `table -> entity -> repository -> endpoint`. Database structures may be serialization identities, append-only facts, links or integrity mechanisms rather than public product objects.

## Correctness-sensitive changes

For capacity, queue selection, scheduling, communications, authority, idempotency, outbox, delivery or contested mutations:

- identify applicable current guarantees and current capability contract;
- preserve accepted READ/PLAN/LOCK/VALIDATE/WRITE/EMIT semantics unless an explicit replacement is designed;
- follow current serialization roots/lock order or explicitly redesign them with concurrency proof;
- use real PostgreSQL evidence for constraints, ranges, locks, isolation, RLS/privileges, leases/fencing and races;
- add regression proof for fixed invariant/race bugs.

During system optimization, `migrations/versions/0001_initial.py` and the historical V3 candidate are not permanent product-shape ceilings. However, do not casually rewrite them during unrelated work. Schema rebaseline is a dedicated controlled operation governed by `docs/architecture/system-optimization-mode.md` and `migrations/README.md` after the complete schema audit.

## Validation before completion

Run the narrowest relevant checks first, then the canonical lane that owns the changed proof.

For Python/architecture/unit/module work:

```bash
python scripts/ci/ci_jobs.py python-quality
```

PostgreSQL/current-product changes additionally run the current PostgreSQL 18 runner described by `docs/testing/README.md` and migration/module instructions.

The Python maintainability signals are non-blocking; deterministic architecture/correctness invariant failures remain blocking.

Exact-head GitHub CI remains merge evidence. Never claim a check passed unless it actually ran against the intended environment.

## Documentation rule

Repository documentation is the system of record. AGENTS files are operational maps, not duplicated architecture manuals.

Historical transition/release documents may retain the tense/status of the checkpoint they document. Current maps, READMEs, CI contracts and AGENTS files must describe the present system and must not treat V3 as an active candidate freeze.
