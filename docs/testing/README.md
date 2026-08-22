# Testing architecture

Request Engine testing separates **where a proof belongs** from **what risk it proves**, while also separating **semantic rigidity** from **implementation flexibility**.

Durable rules:

```text
physical location = ownership / execution boundary
pytest metadata   = evidence class / critical risk
historical/       = pinned release provenance only
HARD boundary     = fail closed unless an explicit stronger contract supersedes it
CONTROLLED shape  = drift alarm; change only with an accepted architecture/product decision
FLEXIBLE shape    = do not freeze incidental filenames/counts/private implementation
```

Key references:

- `docs/testing/repository-governance-contract.md` — normative HARD / CONTROLLED / FLEXIBLE / HISTORICAL classification for repository architecture, DTO/type boundaries, naming, docs and LLM instructions.
- `docs/architecture/pre-production-evolution-policy.md` — normative KEEP / ADAPT / REPLACE / REMOVE / HISTORICAL policy and current-vs-historical distinction.
- `docs/testing/current-guarantees.toml` — machine-readable inventory of current guarantees. It intentionally contains no exact test-file allowlist.
- `docs/testing/current-proof-map.toml` — non-normative mapping from guarantees to representative current proofs.
- `docs/testing/test-architecture-migration.md` — migration/disposition ledger for the V3/F1-to-current test restructuring.
- `tests/AGENTS.md` — executable working rules for placing and authoring tests.

The target is not a particular number of tests. The target is explicit coverage of critical risks with strong, localizable evidence while keeping historical release provenance reproducible and unable to freeze current product evolution.

A new architecture test should answer two questions before it is accepted:

1. **What risk does this assertion protect?**
2. **Is the asserted detail HARD/CONTROLLED, or is it merely FLEXIBLE implementation shape?**

If a legitimate future feature could change the asserted filename/list/count without crossing a semantic boundary, prefer a semantic assertion instead of a snapshot.
