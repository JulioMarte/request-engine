# Request Engine core Python — agent guardrails

These instructions apply to handwritten Python under `src/request_engine/**` and add stricter rules to the repository-root `AGENTS.md`.

## QR-MEGA-001 — HARD mega-file circuit breaker

For handwritten core product Python classified as `domain`, `application`, `contracts`, `api`, or composition/bootstrap/entrypoint code, a new file, threshold crossing, or growth beyond **500 effective code-bearing lines** is a deterministic `INVARIANT_FAILURE` unless the exact path is covered by a bounded exception that already existed in the branch base. Module-root install/composition files are also protected even when the broad metrics classifier labels them `production_other`.

**Self-justification is not authority.** An author or coding agent MUST NOT waive `QR-MEGA-001` with its own rationale, `HEALTHY_AS_IS` verdict, PR description/comment, source comment, generated review text, or by adding/modifying `docs/engineering-quality/mega-file-exceptions.v1.json` in the same implementation change. The gate intentionally reads exceptions from the base ref, so same-change exception edits are invalid for that change.

A source header such as `# @generated`, `# generated file`, or `# DO NOT EDIT` is also **not** exemption authority. Handwritten code does not become generated merely because the author/agent says so in a comment. Generated-code exclusion requires the controlled path/filename conventions recognized by repository tooling; do not move product logic into a generated-looking path or filename to evade quality review.

An implementation change MUST NOT edit the mega-file checker, generated-code classification, CI wiring, exception authority, or this scoped agent policy while also changing core product Python. `QR-MEGA-GOV-001` enforces that separation. If the policy itself needs to evolve, make that a separate governance change, merge it into the integration base, then rebuild/rebase the product implementation against the approved policy.

When `QR-MEGA-001` fires, the agent has only two valid paths:

1. improve the design through a real responsibility/ownership boundary without mechanically fragmenting the code; or
2. stop the implementation and request a separate architecture exception with an exact path, bounded eLOC ceiling, rationale, and approval reference. That exception must be reviewed and merged into the integration base before the implementation is rebuilt/rebased and re-proved.

Do not move business policy into adapters, `platform`, root-level technical files, or another less-protected category merely to escape the 500 eLOC scope. Ownership/layer invariants and semantic review still apply even where the category-specific mega threshold differs.

Do not split a cohesive file into wrappers, one-function helpers, `utils`, `services`, `common`, or other navigation-only fragments merely to get below 500. `QR-NAV-001`, C901 evidence, architecture tests, and semantic review remain counter-pressure against this form of metric gaming.
