"""Shell selectors must not acquire carriage returns from a Windows Python CLI."""

import json
import subprocess
import sys

import pytest


@pytest.mark.parametrize("arguments", [("list",), ("select", "pr"), ("resolve", "smoke")])
def test_registry_stdout_uses_lf_wire_format(arguments: tuple[str, ...]) -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/ci/e2e_suite_registry.py", *arguments],
        check=True,
        capture_output=True,
        timeout=10,
    )
    assert completed.stdout and b"\r" not in completed.stdout
    assert completed.stdout.endswith(b"\n")
    if arguments[0] == "resolve":
        assert json.loads(completed.stdout)["selector"] == "smoke"
    else:
        assert b"smoke\n" in completed.stdout
