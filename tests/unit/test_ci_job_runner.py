from __future__ import annotations

import importlib.util
import os
import shutil
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None, reason="ci job steps execute through bash"
)


def _load_runner_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "ci_jobs_under_test", ROOT / "scripts" / "ci" / "ci_jobs.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _step(key: str, command: str, **kwargs: Any) -> Any:
    runner = _load_runner_module()
    return runner.Step(key=key, name=key, command=command, **kwargs)


def test_passing_step_captures_streamed_output(tmp_path: Path) -> None:
    runner = _load_runner_module()

    result = runner._run_step(
        _step("probe-pass", "echo probe-payload"),
        env=dict(os.environ),
        log_dir=tmp_path,
        verbose=False,
    )

    assert result["status"] == "PASS"
    assert result["returncode"] == 0
    log_text = (tmp_path / "probe-pass.log").read_text(encoding="utf-8")
    assert "probe-payload" in log_text


def test_failing_step_reports_failure_excerpt(tmp_path: Path) -> None:
    runner = _load_runner_module()
    step = _step(
        "probe-fail",
        "echo harmless context; echo 'fatal: probe exploded' >&2; exit 3",
    )

    result = runner._run_step(step, env=dict(os.environ), log_dir=tmp_path, verbose=False)

    assert result["status"] == "FAIL"
    assert result["returncode"] == 3
    log_text = (tmp_path / "probe-fail.log").read_text(encoding="utf-8")
    assert "fatal: probe exploded" in log_text


def test_timed_out_step_is_killed_and_reported(tmp_path: Path) -> None:
    runner = _load_runner_module()
    step = _step("probe-timeout", "sleep 30", timeout_seconds=1)

    result = runner._run_step(step, env=dict(os.environ), log_dir=tmp_path, verbose=False)

    assert result["status"] == "TIMEOUT"
    assert result["returncode"] != 0
    assert float(result["seconds"]) < 10
