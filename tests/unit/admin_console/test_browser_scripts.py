"""Execute UI interaction regressions; this is not real-browser certification."""

import shutil
import subprocess
from pathlib import Path


def test_shipped_browser_scripts_preserve_interaction_boundaries() -> None:
    node = shutil.which("node")
    assert node is not None, "Node is required for admin UI interaction regression proofs"
    directory = Path(__file__).parent
    completed = subprocess.run(
        [
            node,
            "--test",
            str(directory / "admin_script.test.cjs"),
            str(directory / "invitation_script.test.cjs"),
            str(directory / "account_security_script.test.cjs"),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
