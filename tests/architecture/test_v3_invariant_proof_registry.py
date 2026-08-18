import subprocess
import sys


def test_v3_invariant_proof_registry_is_complete_and_owner_bound() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/release/validate_v3_invariant_registry.py"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
