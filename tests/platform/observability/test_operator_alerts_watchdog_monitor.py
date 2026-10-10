import json
import runpy
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pytest

MONITOR = (
    Path(__file__).resolve().parents[3]
    / "scripts"
    / "observability"
    / "operator_alerts_watchdog_monitor.py"
)


def test_read_latest_state_does_not_accept_a_stale_matching_history_entry(
    tmp_path: Path,
) -> None:
    history = tmp_path / "watchdog-state.txt"
    history.write_text("present\nmissing\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(MONITOR), "--read-latest", "--output", str(history)],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == "missing"

    history.write_text("present\nmissing\npresent\n", encoding="utf-8")
    restored = subprocess.run(
        [sys.executable, str(MONITOR), "--read-latest", "--output", str(history)],
        check=True,
        capture_output=True,
        text=True,
    )

    assert restored.stdout.strip() == "present"


def test_read_latest_state_reports_empty_history(tmp_path: Path) -> None:
    history = tmp_path / "watchdog-state.txt"
    history.write_text("", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(MONITOR), "--read-latest", "--output", str(history)],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout == ""


def test_watchdog_heartbeat_requires_actual_receiver_acceptance_and_freshness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    receiver = MONITOR.with_name("operator_alerts_smoke_receiver.py")
    mode_file = tmp_path / "mode"
    mode_file.write_text("accept", encoding="utf-8")
    process = subprocess.Popen(
        [
            sys.executable,
            str(receiver),
            "--port",
            str(port),
            "--output",
            str(tmp_path / "statuses"),
            "--mode-file",
            str(mode_file),
        ]
    )
    module = runpy.run_path(str(MONITOR))
    heartbeat_state = module["_receiver_heartbeat_state"]
    try:
        deadline = time.monotonic() + 5
        while True:
            try:
                with urlopen(f"{origin}/healthz", timeout=1):
                    break
            except (URLError, OSError):
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.02)
        assert heartbeat_state(origin, 15) == "heartbeat_missing"
        payload = {"status": "firing", "alerts": [{"labels": {"alertname": "Watchdog"}}]}
        request = Request(
            f"{origin}/alerts",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=1) as response:
            assert response.status == 200
        with urlopen(f"{origin}/watchdog", timeout=1) as response:
            accepted_at = json.load(response)["last_accepted_timestamp"]
        assert heartbeat_state(origin, 15) == "present"
        mode_file.write_text("fail", encoding="utf-8")
        with pytest.raises(HTTPError) as failure:
            urlopen(request, timeout=1)
        assert failure.value.code == 503
        with urlopen(f"{origin}/watchdog", timeout=1) as response:
            assert json.load(response)["last_accepted_timestamp"] == accepted_at
        # A successful Prometheus rule cannot turn an old accepted receipt fresh.
        with monkeypatch.context() as clock:
            clock.setattr(module["time"], "time", lambda: accepted_at + 16)
            assert heartbeat_state(origin, 15) == "heartbeat_stale"
        mode_file.write_text("accept", encoding="utf-8")
        with urlopen(request, timeout=1):
            pass
        assert heartbeat_state(origin, 15) == "present"
    finally:
        process.terminate()
        process.wait(timeout=5)
    assert heartbeat_state(origin, 15) == "receiver_unreachable"
