#!/usr/bin/env python3
"""Render a bounded systemd timer for native WebAuthn challenge retention."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


class RetentionScheduleError(ValueError):
    """Raised when operator-supplied unit values are not safe to render."""


_SAFE_ABSOLUTE_PATH = re.compile(r"/[A-Za-z0-9_./-]+\Z", re.ASCII)
_SAFE_CALENDAR = re.compile(r"[A-Za-z0-9*,:./ _-]+\Z", re.ASCII)


def _unit_path(name: str, value: Path) -> str:
    resolved = value.resolve().as_posix()
    if not _SAFE_ABSOLUTE_PATH.fullmatch(resolved):
        raise RetentionScheduleError(
            f"{name} must resolve to an absolute path using only letters, digits, /, ., _, and -"
        )
    return resolved


def _calendar(value: str) -> str:
    resolved = value.strip()
    if not resolved or not _SAFE_CALENDAR.fullmatch(resolved):
        raise RetentionScheduleError(
            "on-calendar contains unsupported characters; shell, systemd specifier, "
            "and multiline input are rejected"
        )
    return resolved


def render_units(
    *,
    on_calendar: str,
    repo_root: Path,
    python: Path,
    credential_file: Path,
) -> tuple[str, str]:
    schedule = _calendar(on_calendar)
    repo = _unit_path("repo-root", repo_root)
    python_path = _unit_path("python", python)
    credential_source = _unit_path("credential-file", credential_file)
    retention_script = _unit_path(
        "retention script",
        repo_root.resolve() / "scripts/operations/native_webauthn_challenge_retention.py",
    )

    service = f"""[Unit]
Description=Bounded Request Engine native WebAuthn challenge retention
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
DynamicUser=yes
WorkingDirectory={repo}
LoadCredential=retention-database-url:{credential_source}
Environment=REQUEST_ENGINE_WEBAUTHN_RETENTION_DATABASE_URL_FILE=%d/retention-database-url
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
PrivateDevices=true
ProtectSystem=strict
ProtectHome=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
LockPersonality=true
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
Environment=PYTHONDONTWRITEBYTECODE=1
TimeoutStartSec=90s
ExecStart={python_path} {retention_script} --execute
"""

    timer = f"""[Unit]
Description=Schedule bounded Request Engine native WebAuthn challenge retention

[Timer]
OnCalendar={schedule}
Persistent=true
Unit=request-engine-webauthn-retention.service

[Install]
WantedBy=timers.target
"""
    return service, timer


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--on-calendar", required=True)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--python", required=True)
    parser.add_argument(
        "--credential-file",
        default="/etc/request-engine/webauthn-retention.dsn",
    )
    parser.add_argument("--unit-dir", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    service, timer = render_units(
        on_calendar=args.on_calendar,
        repo_root=Path(args.repo_root),
        python=Path(args.python),
        credential_file=Path(args.credential_file),
    )
    target = Path(args.unit_dir).resolve()
    target.mkdir(parents=True, exist_ok=True)
    service_path = target / "request-engine-webauthn-retention.service"
    timer_path = target / "request-engine-webauthn-retention.timer"
    service_path.write_text(service, encoding="utf-8")
    timer_path.write_text(timer, encoding="utf-8")
    print(service_path)
    print(timer_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
