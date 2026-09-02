# Request Engine core Python — agent guardrails

These instructions apply to handwritten Python under `src/request_engine/**` and add stricter rules to the repository-root `AGENTS.md`.

## QR-MEGA-001 — HARD mega-file circuit breaker

For handwritten core product Python classified as `domain`, `application`, `contracts`, `api`, or composition/bootstrap code, a new file, threshold crossing, or growth beyond **500 effective code-bearing lines** is a deterministic `INVARIANT_FAILURE` unless the exact path is covered by a bounded exception that already existed in the branch base.

**Self-justification is not authority.** An author or coding agent MUST NOT waive `QR-MEGA-001` with its own rationale, `HEALTHY_AS_IS` verdict, PR description/comment, source comment, generated review text, or by adding/modifying `docs/engineering-quality/mega-file-exceptions.v1.json` in the same implementation change. The gate intentionally reads exceptions from the base ref, so same-change exception edits are invalid for that change.

When `QR-MEGA-001` fires, the agent has only two valid paths:

1. improve the design through a real responsibility/ownership boundary without mechanically fragmenting the code; or
2. stop the implementation and request a separate architecture exception with an exact path, bounded eLOC ceiling, rationale, and approval reference. That exception must be reviewed and merged into the integration base before the implementation is rebuilt/rebased and re-proved.

Do not split a cohesive file into wrappers, one-function helpers, `utils`, `services`, `common`, or other navigation-only fragments merely to get below 500. `QR-NAV-001`, C901 evidence, architecture tests, and semantic review remain counter-pressure against this form of metric gaming.
