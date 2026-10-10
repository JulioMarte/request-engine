import subprocess
import sys
from pathlib import Path

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
