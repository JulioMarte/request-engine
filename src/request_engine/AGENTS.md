# Request Engine core Python — agent guardrails

These instructions apply to handwritten Python under `src/request_engine/**` and add path-specific guidance to the repository-root `AGENTS.md`.

## Maintainability metrics are review signals

File LOC, function LOC, McCabe complexity, file count, navigation observations, fan-in, and fan-out are evidence. They are not architecture by themselves.

For changed Python:

```text
effective file LOC > 120
    -> QR-FSIZE-001 REVIEW_CANDIDATE

Ruff C901 McCabe > 10
    -> QR-CPLX-001 REVIEW_CANDIDATE

new direct outbound business-module dependency
    -> QR-COUPLING-001 REVIEW_CANDIDATE
```

Fan-in/fan-out have no numeric blocking threshold. A module may legitimately have high fan-out when it explicitly owns orchestration. `QR-COUPLING-001` is delta-driven and asks for review when the direct dependency neighborhood expands.

When coupling changes, ask whether each new synchronous edge is required, whether ownership remains correct, and whether an existing contract/event/read model expresses the relationship better. Do not hide a real dependency behind a service locator, runtime import, generic shared helper, re-export facade, or forwarding wrapper merely to reduce measured fan-out.

A core file above 500 effective code-bearing lines is an extreme outlier worth careful review, but **500/501 is not a HARD architecture boundary**. The former `QR-MEGA-001 INVARIANT_FAILURE` experiment has been retired during calibration.

When a large or complex file is surfaced:

1. review responsibility and reason to change;
2. inspect real control-flow/side-effect complexity;
3. preserve locality when behavior belongs together;
4. extract only when there is a real ownership/responsibility boundary or a materially clearer reasoning unit;
5. do not target `499`, a lower C901 score, lower fan-out, or a smaller file count as the definition of success.

`HEALTHY_AS_IS` is valid when the evidence does not justify structural change.

## Do not game the sensors

Agents MUST NOT make metrics green by:

- mechanically splitting a cohesive file;
- creating forwarding wrappers or one-function helper modules;
- proliferating interfaces/factories without a real substitution or ownership boundary;
- hiding direct dependencies behind service locators, runtime imports, or re-export facades;
- moving business logic into `platform`, adapters, `shared`, `common`, or utility buckets;
- duplicating logic to avoid a dependency or size signal;
- adding source comments such as `@generated` merely to evade measurement.

Generated-code exclusion uses controlled repository provenance, not author-declared comments.

## Governance changes

Product code and quality-policy files may legitimately change in the same PR. Their co-occurrence is not itself an architecture violation.

However, a change SHOULD NOT weaken a gate in a way that materially changes a verdict from which that same change benefits. When product and policy change together, review that causal relationship explicitly.

Do not weaken deterministic semantic architecture/correctness invariants merely to make a product change pass.

## What remains HARD

A semantic reviewer or LLM cannot waive deterministic invariant failures such as:

- unsupported cross-module internal dependencies;
- unapproved dependency direction;
- dependency cycles;
- inward-layer/framework violations;
- platform/business dependency violations;
- composition bypass of supported module surfaces;
- security, authority, transaction, PostgreSQL, compatibility, and product-contract invariants governed elsewhere.

## Required review path

When deterministic quality tooling emits `REVIEW_CANDIDATE`, follow:

- `docs/engineering-quality/agent-semantic-review-playbook.md`;
- `docs/engineering-quality/semantic-review-protocol.md`.

If remediation changes code, rerun the deterministic architecture, lint/type, and relevant behavior proofs. A lower metric alone is not proof of improvement.
