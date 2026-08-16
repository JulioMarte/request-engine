# Documentation change contract

Status: normative CI/architecture policy.

Request Engine treats selected documentation as part of the executable architecture contract. A pull request that changes a contract-sensitive production surface must update the normative document that defines that surface in the same change.

The machine-readable registry is `docs/architecture/documentation-contracts.toml`. Each rule defines:

- production paths that trigger documentation impact;
- the normative documents that must change with that impact;
- whether all or any of those documents are required.

The canonical architecture suite executes:

```bash
uv run pytest tests/architecture -q
```

`tests/architecture/test_documentation_change_contract.py` runs the documentation checker as part of that required suite. The checker can also be executed directly:

```bash
uv run python scripts/ci/check_documentation_contract.py --base <base-ref>
```

On GitHub pull requests the checker uses `GITHUB_BASE_REF`; if the shallow checkout does not contain that ref it fetches only the required base ref, then compares the base tree directly with the checked-out PR candidate tree. This does not require a merge-base and works with the default shallow `actions/checkout` behavior. Local execution without a base still validates the registry; pass `--base` when you want local change-impact enforcement.

For deterministic fitness tests, `--changed-file <path>` can be repeated to evaluate an explicit synthetic change set. The architecture suite uses this mode to prove both sides of the policy: a worker-runtime code change without its normative document is rejected, while the same code change accompanied by that document is accepted.

## Design constraints

This is deliberately not a rule that every source-code edit needs a documentation edit. The registry must stay focused on architectural, security, operational, public-contract and durable-state boundaries. Pure refactors and implementation details should not create meaningless documentation churn.

A rule is appropriate when code and documentation must evolve atomically for reviewers to understand the actual production contract. Examples include worker credential/fencing semantics, production process composition, public API authority, durable data ownership, and release-evidence semantics.

Required normative documents must already exist. CI fails if the registry refers to a missing document, contains duplicate/incomplete rules, or a contract-sensitive code change omits the required documentation update.

## Extending the contract

When a new production domain becomes normative, add or widen a registry rule in the same pull request that introduces that domain. The rule should use the narrowest stable path patterns that represent the contract surface.

Tests, fixtures, generated evidence, and ordinary implementation files should not be added as triggers unless changing them independently would alter an externally meaningful or operationally authoritative contract.

The documentation fitness gate complements, rather than replaces, architecture tests and executable behavioral evidence. Documentation states the intended contract; tests prove the implementation continues to satisfy it.
