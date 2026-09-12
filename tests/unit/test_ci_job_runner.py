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


def _fake_which(mapping: dict[str, str | None]) -> Any:
    def which(name: str, *args: Any, **kwargs: Any) -> str | None:
        return mapping.get(name)

    return which


def _patch_windows_resolver_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("SYSTEMROOT", str(tmp_path / "Windows"))
    monkeypatch.delenv("REQUEST_ENGINE_GIT_EXEC_PATH", raising=False)
    for variable in ("ProgramFiles", "ProgramFiles(x86)", "LocalAppData"):
        monkeypatch.delenv(variable, raising=False)


def test_windows_resolver_rejects_wsl_bash_launcher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _load_runner_module()
    wsl_bash = tmp_path / "Windows" / "System32" / "bash.exe"
    wsl_bash.parent.mkdir(parents=True)
    wsl_bash.write_bytes(b"")
    _patch_windows_resolver_env(tmp_path, monkeypatch)
    monkeypatch.setattr(shutil, "which", _fake_which({"git": None, "bash": str(wsl_bash)}))

    with pytest.raises(RuntimeError):
        runner._resolve_bash()


def test_windows_resolver_finds_git_bash_without_git_on_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _load_runner_module()
    bash_exe = tmp_path / "Git" / "bin" / "bash.exe"
    bash_exe.parent.mkdir(parents=True)
    bash_exe.write_bytes(b"")
    wsl_bash = tmp_path / "Windows" / "System32" / "bash.exe"
    wsl_bash.parent.mkdir(parents=True)
    wsl_bash.write_bytes(b"")
    _patch_windows_resolver_env(tmp_path, monkeypatch)
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    monkeypatch.setattr(shutil, "which", _fake_which({"git": None, "bash": str(wsl_bash)}))

    resolved = runner._resolve_bash()

    assert Path(resolved) == bash_exe.resolve()


def test_windows_resolver_derives_bash_from_hook_git_exec_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _load_runner_module()
    bash_exe = tmp_path / "Git" / "bin" / "bash.exe"
    bash_exe.parent.mkdir(parents=True)
    bash_exe.write_bytes(b"")
    exec_path = tmp_path / "Git" / "mingw64" / "libexec" / "git-core"
    exec_path.mkdir(parents=True)
    wsl_bash = tmp_path / "Windows" / "System32" / "bash.exe"
    wsl_bash.parent.mkdir(parents=True)
    wsl_bash.write_bytes(b"")
    _patch_windows_resolver_env(tmp_path, monkeypatch)
    monkeypatch.setenv("REQUEST_ENGINE_GIT_EXEC_PATH", str(exec_path))
    monkeypatch.setattr(shutil, "which", _fake_which({"git": None, "bash": str(wsl_bash)}))

    resolved = runner._resolve_bash()

    assert Path(resolved) == bash_exe.resolve()
