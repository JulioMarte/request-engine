from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import cast

import pytest

ROOT = Path(__file__).resolve().parents[3]
RENDERER = ROOT / "scripts/operations/render_native_webauthn_retention_systemd.py"
RETENTION_COMMAND = ROOT / "scripts/operations/native_webauthn_challenge_retention.py"


def _load(path: Path, module_name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_render_units_is_unprivileged_bounded_and_keeps_credentials_out_of_unit(
    tmp_path: Path,
) -> None:
    renderer = _load(RENDERER, "retention_systemd_renderer_test_target")
    service, timer = renderer.render_units(  # type: ignore[attr-defined]
        on_calendar="*-*-* 03:15:00",
        repo_root=tmp_path / "request-engine",
        python=tmp_path / "request-engine/.venv/bin/python",
        credential_file=Path("/etc/request-engine/webauthn-retention.dsn"),
    )

    assert "DynamicUser=yes" in service
    assert "NoNewPrivileges=true" in service
    assert "ProtectSystem=strict" in service
    assert "ProtectHome=true" in service
    assert "TimeoutStartSec=90s" in service
    assert "--execute" in service
    assert (
        "LoadCredential=retention-database-url:/etc/request-engine/webauthn-retention.dsn"
        in service
    )
    assert (
        "REQUEST_ENGINE_WEBAUTHN_RETENTION_DATABASE_URL_FILE=%d/retention-database-url" in service
    )
    assert "DATABASE_URL=" not in service
    assert "Password" not in service
    assert "OnCalendar=*-*-* 03:15:00" in timer
    assert "Persistent=true" in timer
    assert "Unit=request-engine-webauthn-retention.service" in timer


@pytest.mark.parametrize(
    "hostile", ["$HOME", "%n", "evil;ExecStart=/bin/sh", "line\nExecStart=/bin/sh"]
)
def test_renderer_rejects_calendar_injection(tmp_path: Path, hostile: str) -> None:
    renderer = _load(RENDERER, "retention_calendar_injection_test_target")
    error = cast(type[ValueError], renderer.RetentionScheduleError)  # type: ignore[attr-defined]
    with pytest.raises(error, match="unsupported characters"):
        renderer.render_units(  # type: ignore[attr-defined]
            on_calendar=hostile,
            repo_root=tmp_path,
            python=Path("/usr/bin/python3"),
            credential_file=Path("/etc/request-engine/webauthn-retention.dsn"),
        )


@pytest.mark.parametrize(
    "hostile", ["repo$HOME", "repo%n", 'repo";ExecStart=/bin/sh', "repo\\path"]
)
@pytest.mark.parametrize("field", ["repo_root", "python", "credential_file"])
def test_renderer_rejects_systemd_path_expansion_and_quoting(
    tmp_path: Path, hostile: str, field: str
) -> None:
    renderer = _load(RENDERER, "retention_path_injection_test_target")
    error = cast(type[ValueError], renderer.RetentionScheduleError)  # type: ignore[attr-defined]
    values = {
        "repo_root": tmp_path,
        "python": Path("/usr/bin/python3"),
        "credential_file": Path("/etc/request-engine/webauthn-retention.dsn"),
    }
    values[field] = tmp_path / hostile if field == "repo_root" else Path("/") / hostile
    with pytest.raises(error, match="absolute path"):
        renderer.render_units(  # type: ignore[attr-defined]
            on_calendar="daily",
            **values,
        )


def test_retention_command_never_emits_dsn_or_exception_details(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    command = _load(RETENTION_COMMAND, "retention_command_secret_test_target")
    secret_dsn = "postgresql://retention:do-not-log@example.invalid/request_engine"
    credential = tmp_path / "retention.dsn"
    credential.write_text(secret_dsn + "\n", encoding="utf-8")
    monkeypatch.delenv("REQUEST_ENGINE_WEBAUTHN_RETENTION_DATABASE_URL", raising=False)
    monkeypatch.setenv("REQUEST_ENGINE_WEBAUTHN_RETENTION_DATABASE_URL_FILE", str(credential))
    monkeypatch.setattr("sys.argv", [str(RETENTION_COMMAND), "--execute"])

    def fail_with_secret(dsn: str, **_kwargs: object) -> int:
        assert dsn == secret_dsn
        raise RuntimeError(secret_dsn)

    monkeypatch.setattr(command, "_run", fail_with_secret)
    assert command.main() == 1  # type: ignore[attr-defined]
    captured = capsys.readouterr()
    assert captured.err.strip() == "native_webauthn_challenge_retention_failed"
    assert secret_dsn not in captured.out + captured.err


def test_ambiguous_or_multiline_credentials_fail_closed_without_logging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    command = _load(RETENTION_COMMAND, "retention_command_credential_validation_test_target")
    secret_dsn = "postgresql://retention:secret-value@example.invalid/request_engine"
    credential = tmp_path / "retention.dsn"
    credential.write_text(secret_dsn + "\nmalicious=setting\n", encoding="utf-8")
    monkeypatch.setenv("REQUEST_ENGINE_WEBAUTHN_RETENTION_DATABASE_URL", secret_dsn)
    monkeypatch.setenv("REQUEST_ENGINE_WEBAUTHN_RETENTION_DATABASE_URL_FILE", str(credential))
    monkeypatch.setattr("sys.argv", [str(RETENTION_COMMAND), "--execute"])

    database_called = False

    def database_must_not_run(*_args: object, **_kwargs: object) -> int:
        nonlocal database_called
        database_called = True
        return 0

    monkeypatch.setattr(command, "_run", database_must_not_run)
    assert command.main() == 1  # type: ignore[attr-defined]
    captured = capsys.readouterr()
    assert not database_called
    assert captured.err.strip() == "native_webauthn_challenge_retention_failed"
    assert secret_dsn not in captured.out + captured.err
    assert "malicious" not in captured.out + captured.err


def test_multiline_credential_file_fails_before_database_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    command = _load(RETENTION_COMMAND, "retention_command_multiline_file_test_target")
    secret_dsn = "postgresql://retention:secret-value@example.invalid/request_engine"
    credential = tmp_path / "retention.dsn"
    credential.write_text(secret_dsn + "\nmalicious=setting\n", encoding="utf-8")
    monkeypatch.delenv("REQUEST_ENGINE_WEBAUTHN_RETENTION_DATABASE_URL", raising=False)
    monkeypatch.setenv("REQUEST_ENGINE_WEBAUTHN_RETENTION_DATABASE_URL_FILE", str(credential))
    monkeypatch.setattr("sys.argv", [str(RETENTION_COMMAND), "--execute"])

    database_called = False

    def database_must_not_run(*_args: object, **_kwargs: object) -> int:
        nonlocal database_called
        database_called = True
        return 0

    monkeypatch.setattr(command, "_run", database_must_not_run)
    assert command.main() == 1  # type: ignore[attr-defined]
    captured = capsys.readouterr()
    assert not database_called
    assert captured.err.strip() == "native_webauthn_challenge_retention_failed"
    assert secret_dsn not in captured.out + captured.err
    assert "malicious" not in captured.out + captured.err


def test_malicious_environment_configuration_fails_before_database_call(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    command = _load(RETENTION_COMMAND, "retention_command_config_test_target")
    secret_dsn = "postgresql://retention:secret-value@example.invalid/request_engine"
    monkeypatch.setenv("REQUEST_ENGINE_WEBAUTHN_RETENTION_DATABASE_URL", secret_dsn)
    monkeypatch.setenv("REQUEST_ENGINE_WEBAUTHN_CHALLENGE_RETENTION_SECONDS", "604800\n--execute")
    monkeypatch.setattr("sys.argv", [str(RETENTION_COMMAND), "--execute"])

    database_called = False

    def database_must_not_run(*_args: object, **_kwargs: object) -> int:
        nonlocal database_called
        database_called = True
        return 0

    monkeypatch.setattr(command, "_run", database_must_not_run)
    assert command.main() == 1  # type: ignore[attr-defined]
    captured = capsys.readouterr()
    assert not database_called
    assert captured.err.strip() == "native_webauthn_challenge_retention_failed"
    assert secret_dsn not in captured.out + captured.err
    assert "--execute" not in captured.out + captured.err
