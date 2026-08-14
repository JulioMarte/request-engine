from pathlib import Path


WORKFLOWS_DIR = Path(".github/workflows")
FORBIDDEN_RUNNERS = ("windows", "macos", "self-hosted")


def _workflow_files() -> tuple[Path, ...]:
    return tuple(
        sorted(
            path
            for path in WORKFLOWS_DIR.iterdir()
            if path.is_file() and path.suffix in {".yml", ".yaml"}
        )
    )


def test_github_actions_use_only_linux_ubuntu_runners() -> None:
    workflows = _workflow_files()
    assert workflows, "at least one GitHub Actions workflow is required"

    violations: list[str] = []
    for workflow in workflows:
        content = workflow.read_text(encoding="utf-8")
        lowered = content.lower()

        for forbidden in FORBIDDEN_RUNNERS:
            if forbidden in lowered:
                violations.append(f"{workflow}: forbidden runner family {forbidden!r}")

        runner_values: list[str] = []
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped.startswith("runs-on:"):
                continue
            value = stripped.removeprefix("runs-on:").strip().strip("'\"")
            runner_values.append(value)

        if not runner_values:
            violations.append(f"{workflow}: no explicit runs-on values found")
            continue

        for runner in runner_values:
            if not runner.startswith("ubuntu-"):
                violations.append(
                    f"{workflow}: runs-on must be an explicit ubuntu-* value, got {runner!r}"
                )

    assert not violations, "\n".join(violations)
