"""Actual Bash waiters must honor their deadlines under strict unset checking."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts/ci/operator_alerts_smoke.sh"


@pytest.mark.parametrize(
    ("waiter", "arguments"),
    [
        ("wait_receiver_status", "firing Watchdog"),
        ("wait_prom_alert", "Watchdog"),
        ("wait_prom_metric_positive", "probe_metric"),
        ("wait_for_watchdog_state", "present"),
    ],
)
@pytest.mark.parametrize("ready", [True, False])
def test_waiter_initializes_budget_before_deadline_and_exits_bounded(
    tmp_path: Path, waiter: str, arguments: str, ready: bool
) -> None:
    # This excludes real service semantics. Run the actual shell functions
    # against ready/unready boundaries to protect nounset and timeout behavior.
    definitions = "\n".join(
        name
        + "() {"
        + SCRIPT.read_text(encoding="utf-8").split(name + "() {", 1)[1].split("\n}\n", 1)[0]
        + "\n}\n"
        for name in (
            "wait_receiver_status",
            "wait_prom_alert",
            "wait_prom_metric_positive",
            "wait_for_watchdog_state",
        )
    )
    receipts = tmp_path / "receiver-statuses.txt"
    receipts.write_text("firing|Watchdog\n" if ready else "", encoding="utf-8")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    curl = fake_bin / "curl"
    curl.write_text(
        '#!/bin/sh\nprintf \'{"status":"success","data":{"result":[{}]}}\\n\'\n',
        encoding="utf-8",
    )
    curl.chmod(0o755)
    python = fake_bin / "python3"
    python.write_text(
        '#!/bin/sh\ncase "$1" in *operator_alerts_watchdog_monitor.py) '
        'echo present ;; *) exec "$REAL_PYTHON" "$@" ;; esac\n',
        encoding="utf-8",
    )
    python.chmod(0o755)
    environment = {key: value for key, value in os.environ.items() if key != "seconds"}
    result = subprocess.run(
        [
            "bash",
            "-c",
            "set -euo pipefail\n"
            + definitions
            + '\nTMP_DIR="$TEST_TMP"; ROOT_DIR="$TEST_TMP"; probe_file="$TEST_TMP/probe"\n'
            + f"{waiter} {arguments} {2 if ready else 0}\n",
        ],
        env={
            **environment,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "REAL_PYTHON": sys.executable,
            "TEST_TMP": str(tmp_path),
        },
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == (0 if ready else 1), result.stderr
    assert "unbound variable" not in result.stderr
    if not ready:
        assert "did not" in result.stderr
