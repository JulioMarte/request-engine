# V3 CI runner policy

## Decision

Request Engine CI runs only on Linux GitHub-hosted Ubuntu runners.

Allowed `runs-on` values must be explicit strings that start with:

```text
ubuntu-
```

The current default is `ubuntu-latest`.

## Explicitly unsupported

CI must not use:

- Windows runners;
- macOS runners;
- self-hosted runners;
- OS matrices;
- expressions that can resolve to another operating system;
- any runner family other than GitHub-hosted Ubuntu.

This restriction applies to every workflow under `.github/workflows/`.

## Enforcement

`tests/architecture/test_ci_linux_only.py` scans every GitHub Actions workflow.

The architecture gate fails if a job does not use an explicit Ubuntu runner string. It also fails if a job introduces an OS matrix.

This is a repository invariant, not a temporary workflow convention.

## Rationale

Request Engine does not require platform-specific CI behavior. A single Linux CI platform reduces duplicated configuration, inconsistent tool behavior, and unnecessary runner cost while preserving the PostgreSQL and Python execution environment used by the service.
