"""Blocked authentication calls must not create additional durable state."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize(
    ("challenges", "sessions", "accepted_attempts", "passes"),
    [(3, 0, 3, True), (4, 0, 3, False), (3, 1, 3, False), (3, 0, 4, False)],
)
def test_authoritative_admission_oracle(
    tmp_path: Path, challenges: int, sessions: int, accepted_attempts: int, passes: bool
) -> None:
    # Exercise the driver's actual parser with authoritative-state samples.
    # Container routing and PostgreSQL provenance belong to the Docker CI lane.
    script = (ROOT / "scripts/ci/run_e2e_network_boundary.sh").read_text(encoding="utf-8")
    parser = script.split('python - "$state"', 1)[1].split("<<'PY'\n", 1)[1].split("\nPY", 1)[0]
    state = {
        "configured_limit": 3,
        "accepted_attempts": accepted_attempts,
        "challenges": challenges,
        "sessions": sessions,
    }
    output = tmp_path / "evidence.json"
    result = subprocess.run(
        [sys.executable, "-c", parser, json.dumps(state), str(output)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode == 0) is passes, result.stderr
    assert output.exists() is passes
