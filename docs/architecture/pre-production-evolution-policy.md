# Request Engine — Pre-Production Evolution and Adversarial Proof Policy

Status: normative repository/product-evolution policy while Request Engine has no customer-owned production data or externally committed compatibility contract.

## 1. Why this policy exists

Request Engine V3 was deliberately frozen and release-proven to force architectural discipline, expose hidden race/invariant failures, and establish a reproducible baseline.

That work succeeded at its original purpose. It also exposed a product reality: the first baseline did not contain every capability required for Request Engine to satisfy its intended role. Operational profile, contextual supply and later capabilities are not optional polish; some are foundational corrections or extensions discovered only after exercising the system as a whole.

Therefore the released V3 baseline is **historical/release provenance, not a permanent ceiling on product architecture**.

While Request Engine has no customer-owned production data and no externally promised compatibility contract, the repository should optimize for building the correct durable system rather than preserving accidental incompleteness merely because a previous baseline was proven.

## 2. Core rule

```text
freeze the evidence, not the future
```

A prior release proof may establish that a specific tree behaved correctly according to its then-current contract. It does not establish that the contract is forever complete or that later features must preserve every entity shape, module edge, public-surface snapshot, migration-head assumption or test allowlist unchanged.

A justified post-baseline feature may deliberately supersede a previous architectural/product rule when all of the following are true:

1. the old rule materially prevents or distorts a required capability;
2. the replacement contract is documented before or with implementation;
3. affected invariants, authority boundaries and transaction semantics are dispositioned old -> new;
4. tests are changed to protect the intended guarantee rather than the obsolete implementation shape;
5. compatibility consequences are explicit;
6. exact-head CI proves the replacement architecture adversarially.

Changing an architectural rule is not a test bypass. It is a controlled contract evolution.

## 3. What remains immutable provenance

The following may remain immutable **as historical evidence** even when current product semantics move beyond them:

```text
released migration/release artifacts
frozen release-candidate snapshots
release manifests and proof registries
historical ADR decisions and their status at the time
historical schema fingerprints
old release matrices
```

Examples include the released V3 `0001_initial`, frozen V3 candidate and G01-G20 evidence.

Historical provenance must remain reproducible enough to answer:

```text
what exactly did we prove then?
```

It must not be misused to answer a different question:

```text
what is Request Engine allowed to become now?
```

## 4. Greenfield/pre-production freedom

Until Request Engine has customer-owned production data or an explicit external compatibility commitment, a feature may, when justified:

- introduce new entities or retire obsolete conceptual structures;
- change module ownership or approved dependency edges;
- replace public/internal capability shapes;
- add new error codes and capability versions;
- evolve transaction protocols and lock topology;
- change schema beyond the released baseline using the appropriate migration/rebaseline strategy;
- replace tests that encode obsolete architecture;
- remove redundant proof paths;
- simplify historical compatibility machinery that no longer protects a real obligation.

This freedom is **not** permission to weaken correctness. The burden moves from “preserve old shape” to “prove the new system is safe and coherent.”

## 5. Test classification

Every durable test should be understood by the risk it protects.

### 5.1 Safety/invariant tests — preserve or strengthen

These protect properties such as:

```text
tenant isolation / foreign-row opacity
authorization and representation authority
idempotency
atomicity / rollback safety
capacity ownership
race serialization / lock ordering
immutability of committed historical facts
provenance integrity
crash/retry safety
outbox/event durability
half-open interval semantics
DST/timezone correctness
least privilege / RLS / runtime ACLs
public privacy guarantees
```

They should normally survive architectural evolution. If their implementation changes, replace them with evidence that protects the same or stronger invariant.

### 5.2 Contract tests — evolve with the accepted contract

These protect intentionally supported behavior or interfaces.

When a contract is deliberately superseded, the test must be updated to the new contract. It is incorrect to keep the old assertion merely because it once passed.

For an externally committed/customer-visible contract, compatibility policy may require versioning or migration rather than replacement. Until such commitment exists, the repository may intentionally break the old internal/pre-production contract when the new design is superior and documented.

### 5.3 Architecture fitness functions — alarms, not constitutional locks

Architecture tests should detect unreviewed drift:

```text
unexpected module edge
layer violation
new transport/persistence coupling
undocumented public surface
unreviewed branch/integration topology
```

They must not make an accepted architecture impossible to change.

When the architecture intentionally changes, update:

```text
normative architecture docs
ownership / connection-surface contract
fitness-function policy
architecture tests
```

in the same coherent change.

The correct question is not “does the new design match the old allowlist?” but “does the new design preserve clear ownership, acyclic dependencies, explicit trust boundaries and testable connection surfaces?”

### 5.4 Release-provenance tests — pin to the historical release

A historical V3 proof should test V3 specifically, for example by installing/pinning the released V3 revision or comparing against the frozen V3 baseline.

It should **not** require current post-V3 product head to remain structurally identical to V3.

Historical release tests answer regression/provenance questions; current product tests answer current correctness questions.

### 5.5 Snapshot/allowlist/shape tests — lowest authority

Tests that assert exact lists, exact file counts, exact migration head assumptions, exact capability inventories, exact module edges or other repository shape are useful only while that shape is itself normative.

If the shape changes intentionally, these tests must evolve. They may never silently override a newer accepted product contract.

### 5.6 Redundant tests — consolidate deliberately

Duplicate tests are not automatically additional safety. Redundancy that repeats the same invariant through the same path increases CI cost and maintenance noise without materially increasing confidence.

A redundant test may be removed when its protected guarantee is explicitly mapped to a surviving test or stronger end-to-end/adversarial proof.

Never delete a failing test merely to make CI green.

## 6. Required test disposition for intentional architecture changes

When an architectural/product feature conflicts with existing tests, classify each affected test:

```text
KEEP       still protects a valid invariant
ADAPT      invariant remains but implementation/contract changed
REPLACE    old test is structurally obsolete; new adversarial proof supersedes it
REMOVE     genuinely redundant or protects an intentionally retired promise
HISTORICAL keep only in release-provenance lane, not current-product gate
```

For `ADAPT`, `REPLACE` or `REMOVE`, document the protected intent and where that intent is proven after the change.

A CI green obtained by deleting assertions without such disposition is not valid evidence.

## 7. Adversarial suite philosophy

The primary purpose of Request Engine CI is not to reward architectural conformity. It is to **falsify unsafe designs before users can encounter them**.

Feature suites should therefore prefer adversarial scenarios over broad shallow duplication.

For every meaningful state-changing capability, ask at minimum:

```text
What if the relevant configuration changes after discovery but before commit?
What if two actors execute the operation concurrently?
What if the same command is retried?
What if a foreign-tenant identifier is supplied?
What if the transaction crashes after partial work?
What if an event/worker runs late, twice, or out of order?
What historical facts must remain reconstructable after mutable state changes?
What lock/order inversion could deadlock or produce split ownership?
What invalid database state can direct SQL or a bug attempt to create?
What happens at timezone/DST and half-open interval boundaries?
```

The goal is a smaller set of high-value proofs that attack the weak points of the design, plus targeted unit/contract tests where they provide fast localization.

## 8. Current-vs-historical CI lanes

CI should distinguish at least conceptually:

```text
CURRENT PRODUCT PROOF
  validates current production head and accepted current contracts

HISTORICAL COMPATIBILITY / RELEASE PROVENANCE
  proves old released guarantees remain reproducible where still valuable
```

A historical lane must not prevent current product evolution merely because new objects, capabilities or migrations exist.

A current-product lane must not weaken tenant/security/transaction invariants merely because historical compatibility is inconvenient.

## 9. Migration and compatibility posture

No-customer status removes many migration constraints, but not the need for clarity.

For each major schema/contract change choose explicitly:

```text
append-only migration
intentional rebaseline before first customer deployment
versioned public contract
intentional breaking pre-production replacement
```

Do not preserve complexity solely to simulate compatibility obligations that do not exist.

Conversely, once real customer-owned data or an external compatibility promise exists, this policy must be revisited. At that point destructive rebaseline/breaking changes require an explicit migration/versioning strategy and production rollback/forward-safety analysis.

## 10. Architecture-change evidence bundle

A change that intentionally supersedes a previous architectural restriction is merge-ready only when the PR contains enough evidence to answer:

```text
OLD RULE
What did the previous architecture/test require?

WHY INSUFFICIENT
Which real product capability or correctness property did it prevent/distort?

NEW CONTRACT
What is authoritative now?

INVARIANT DISPOSITION
Which guarantees survive, change, disappear or become stronger?

TEST DISPOSITION
KEEP / ADAPT / REPLACE / REMOVE / HISTORICAL for affected proofs.

ADVERSARIAL PROOF
Which races, authority boundaries, retries, failures and provenance paths attack the new design?

COMPATIBILITY DECISION
What historical/current compatibility is actually required?

EXACT-HEAD CI
Does the final integrated candidate pass the current-product and relevant historical lanes?
```

## 11. Rules that must not become arbitrary gates

Repository rules should not block a justified change solely because:

- a previous snapshot had a smaller capability list;
- a module dependency allowlist has not yet been updated;
- a historical release test assumes `alembic head` equals an old release;
- a generated file inventory changed;
- a feature adds a new public error code;
- an old architecture document says a concept was out of scope before the product need was understood;
- a duplicated test is removed while its invariant remains strongly proven elsewhere.

Such failures are prompts to reconcile policy and evidence, not reasons to preserve an incorrect architecture.

## 12. Rules that remain hard by default

The following remain hard constraints unless an explicit newer contract replaces them with an equal-or-stronger safety model:

```text
tenant isolation and opacity
explicit authority
transactional atomicity
single authoritative capacity ownership
idempotency for externally retried commands
immutable historical commitments/provenance where promised
least privilege
bounded/defined failure semantics
acyclic/understandable ownership topology
observable and reproducible failure handling
adversarial race proof for contested state
```

These are system-quality properties, not artifacts of V3.

## 13. Exit condition for this policy

This greenfield/pre-production freedom is valid while Request Engine has no customer-owned production data and no external contract requiring backward compatibility.

Before first production customer deployment, create an explicit production-evolution policy defining:

```text
schema migration compatibility
API/capability versioning
rollback/roll-forward guarantees
data retention and provenance obligations
deprecation policy
customer-visible breaking-change policy
release support window
```

At that point “we have no users” stops being an admissible justification for destructive evolution.
