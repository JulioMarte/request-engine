from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import cast

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[3]
    / "scripts"
    / "operations"
    / "render_recovery_backup_systemd.py"
)


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("recovery_systemd_test_target", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_render_units_requires_explicit_schedule_and_retention(tmp_path: Path) -> None:
    module = _module()
    service, timer = module.render_units(  # type: ignore[attr-defined]
        on_calendar="*-*-* 02:15:00",
        local_retention_days=21,
        repo_root=tmp_path / "request-engine",
        python=Path("/usr/bin/python3"),
        environment_file=Path("/etc/request-engine/recovery-backup.env"),
        backup_output_dir=tmp_path / "backups",
    )

    assert "OnCalendar=*-*-* 02:15:00" in timer
    assert "Persistent=true" in timer
    assert "--local-retention-days 21" in service
    assert "recovery_bundle.py" in service
    assert "EnvironmentFile=\"/etc/request-engine/recovery-backup.env\"" in service
    assert "UMask=0077" in service
    assert "NoNewPrivileges=true" in service


def test_render_units_rejects_non_positive_retention(tmp_path: Path) -> None:
    module = _module()
    error = cast(type[ValueError], module.RecoveryScheduleError)  # type: ignore[attr-defined]
    with pytest.raises(error, match="retention days"):
        module.render_units(  # type: ignore[attr-defined]
            on_calendar="daily",
            local_retention_days=0,
            repo_root=tmp_path,
            python=Path("/usr/bin/python3"),
            environment_file=Path("/etc/request-engine/recovery-backup.env"),
            backup_output_dir=tmp_path / "backups",
        )


def test_render_units_rejects_multiline_schedule(tmp_path: Path) -> None:
    module = _module()
    error = cast(type[ValueError], module.RecoveryScheduleError)  # type: ignore[attr-defined]
    with pytest.raises(error, match="single-line"):
        module.render_units(  # type: ignore[attr-defined]
            on_calendar="daily\nOnFailure=evil.service",
            local_retention_days=7,
            repo_root=tmp_path,
            python=Path("/usr/bin/python3"),
            environment_file=Path("/etc/request-engine/recovery-backup.env"),
            backup_output_dir=tmp_path / "backups",
        )
