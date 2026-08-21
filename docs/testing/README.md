# Testing architecture

Request Engine testing separates **where a proof belongs** from **what risk it proves**.

Durable rules:

```text
physical location = ownership / execution boundary
pytest metadata   = evidence class / critical risk
historical/       = pinned release provenance only
```

Key references:

- `docs/architecture/pre-production-evolution-policy.md` — normative KEEP / ADAPT / REPLACE / REMOVE / HISTORICAL policy and current-vs-historical distinction.
- `docs/testing/current-guarantees.toml` — machine-readable inventory of current guarantees. It intentionally contains no exact test-file allowlist.
- `docs/testing/test-architecture-migration.md` — temporary migration/disposition ledger for the V3/F1-to-current test restructuring.
- `tests/AGENTS.md` — executable working rules for placing and authoring tests.

The target is not a particular number of tests. The target is explicit coverage of critical risks with strong, localizable evidence while keeping historical release provenance reproducible and unable to freeze current product evolution.
