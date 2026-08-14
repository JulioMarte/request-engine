from pathlib import Path

import yaml


WORKFLOWS_DIR = Path(".github/workflows")
ALLOWED_RUNNER_PREFIXES = ("ubuntu-",)


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
        document = yaml.safe_load(workflow.read_text(encoding="utf-8")) or {}
        jobs = document.get("jobs", {})
        assert isinstance(jobs, dict), f"{workflow} must define a jobs mapping"

        for job_name, job in jobs.items():
            if not isinstance(job, dict):
                violations.append(f"{workflow}:{job_name}: job must be a mapping")
                continue

            runner = job.get("runs-on")
            if not isinstance(runner, str):
                violations.append(
                    f"{workflow}:{job_name}: runs-on must be an explicit Ubuntu runner string"
                )
                continue

            if not runner.startswith(ALLOWED_RUNNER_PREFIXES):
                violations.append(
                    f"{workflow}:{job_name}: forbidden runner {runner!r}; CI is Ubuntu/Linux only"
                )

            strategy = job.get("strategy")
            if isinstance(strategy, dict):
                matrix = strategy.get("matrix")
                if isinstance(matrix, dict) and "os" in matrix:
                    violations.append(
                        f"{workflow}:{job_name}: OS matrices are forbidden; use one Ubuntu runner"
                    )

    assert not violations, "\n".join(violations)
