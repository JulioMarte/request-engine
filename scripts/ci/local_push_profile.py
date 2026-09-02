from __future__ import annotations

PROFILE_VERSION = "local-push-cert/v1"

# Reuse the canonical python-quality step definitions from ci_jobs.py instead of
# duplicating commands in the local publish gate. Keep this profile deliberately
# bounded: it should catch cheap/high-signal publication defects without turning
# every push into a full release proof.
PYTHON_QUALITY_STEPS: tuple[str, ...] = (
    "file-budget",
    "uv-sync",
    "lockfile",
    "ruff-lint",
    "ruff-format",
    "pyright",
    "secret-scan",
    "python-sast",
    "architecture",
    "unit",
    "modules",
)

# Intentionally remote-only during the initial ergonomics calibration. The
# dependency audit can require vulnerability-database/network work and the
# PostgreSQL/concurrency/release lanes are materially more expensive.
REMOTE_ONLY_PYTHON_QUALITY_STEPS: tuple[str, ...] = ("dependency-audit",)

POLICY_SEPARATION_SCRIPT = "scripts/ci/check_quality_policy_separation.py"


def ci_job_arguments() -> list[str]:
    args = ["python", "scripts/ci/ci_jobs.py", "python-quality"]
    for step in PYTHON_QUALITY_STEPS:
        args.extend(("--step", step))
    return args
