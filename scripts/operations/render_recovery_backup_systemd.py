#!/usr/bin/env python3
"""Render explicit systemd automation for Request Engine recovery backups."""

from __future__ import annotations

import argparse
from pathlib import Path


class RecoveryScheduleError(ValueError):
    pass


def _clean(name: str, value: str) -> str:
    resolved = value.strip()
    if not resolved or "\n" in value or "\r" in value or "\x00" in value:
        raise RecoveryScheduleError(f"{name} must be a non-empty single-line value")
    return resolved


def _positive_days(value: str) -> int:
    try:
        days = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("retention days must be an integer") from exc
    if days <= 0:
        raise argparse.ArgumentTypeError("retention days must be positive")
    return days


def _systemd_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render_units(
    *,
    on_calendar: str,
    local_retention_days: int,
    repo_root: Path,
    python: Path,
    environment_file: Path,
    backup_output_dir: Path,
) -> tuple[str, str]:
    schedule = _clean("on-calendar", on_calendar)
    if local_retention_days <= 0:
        raise RecoveryScheduleError("local retention days must be positive")

    repo = str(repo_root.resolve())
    python_path = str(python.resolve())
    env_file = str(environment_file)
    backup_dir = str(backup_output_dir.resolve())
    command = " ".join(
        (
            _systemd_quote(python_path),
            _systemd_quote(f"{repo}/scripts/operations/recovery_bundle.py"),
            "backup",
            "--output-dir",
            _systemd_quote(backup_dir),
            "--local-retention-days",
            str(local_retention_days),
        )
    )

    service = f"""[Unit]
Description=Request Engine encrypted PostgreSQL and OpenBao recovery backup
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
WorkingDirectory={_systemd_quote(repo)}
EnvironmentFile={_systemd_quote(env_file)}
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ExecStart={command}
"""

    timer = f"""[Unit]
Description=Schedule Request Engine recovery backups

[Timer]
OnCalendar={schedule}
Persistent=true
Unit=request-engine-recovery-backup.service

[Install]
WantedBy=timers.target
"""
    return service, timer


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--on-calendar", required=True)
    parser.add_argument("--local-retention-days", required=True, type=_positive_days)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--python", default="/usr/bin/python3")
    parser.add_argument(
        "--environment-file",
        default="/etc/request-engine/recovery-backup.env",
    )
    parser.add_argument("--backup-output-dir", required=True)
    parser.add_argument("--unit-dir", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    service, timer = render_units(
        on_calendar=args.on_calendar,
        local_retention_days=args.local_retention_days,
        repo_root=Path(args.repo_root),
        python=Path(args.python),
        environment_file=Path(args.environment_file),
        backup_output_dir=Path(args.backup_output_dir),
    )
    target = Path(args.unit_dir).resolve()
    target.mkdir(parents=True, exist_ok=True)
    service_path = target / "request-engine-recovery-backup.service"
    timer_path = target / "request-engine-recovery-backup.timer"
    service_path.write_text(service, encoding="utf-8")
    timer_path.write_text(timer, encoding="utf-8")
    print(service_path)
    print(timer_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
