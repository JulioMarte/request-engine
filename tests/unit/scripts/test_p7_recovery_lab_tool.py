"""Shell-adapter regressions; PostgreSQL archive semantics run in the live lab."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

WRAPPER = Path(__file__).resolve().parents[3] / "scripts/ci/p7_recovery_lab_tool.sh"

pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="symlinks the shell wrapper (WinError 1314 without privilege), execs shebang "
    "shims via colon PATH and asserts POSIX 0o600 modes; runs on Linux CI",
)


@pytest.mark.parametrize("mode,expected_status", [("valid", 0), ("empty", 1), ("invalid", 1)])
def test_dump_streams_to_host_and_requires_successful_archive_parse(
    tmp_path: Path, mode: str, expected_status: int
) -> None:
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    (binary_dir / "pg_dump").symlink_to(WRAPPER)
    docker = binary_dir / "docker"
    docker.write_text(
        """#!/usr/bin/env python3
import os, sys
from pathlib import Path
arguments = sys.argv[1:]
if 'pg_dump' in arguments:
    # A --file argument directs bytes into that literal file, not stdout.
    for argument in arguments:
        if argument.startswith('--file='):
            Path(argument.split('=', 1)[1]).write_bytes(b'PGDMPfixture')
            raise SystemExit(0)
    mode = os.environ['ARCHIVE_MODE']
    payload = {'valid': b'PGDMPfixture', 'invalid': b'bad', 'empty': b''}[mode]
    sys.stdout.buffer.write(payload)
elif 'pg_restore' in arguments and '--list' in arguments:
    archive = sys.stdin.buffer.read()
    Path(os.environ['PARSED_INPUT']).write_bytes(archive)
    raise SystemExit(0 if archive == b'PGDMPfixture' else 1)
else:
    raise SystemExit(2)
""",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    output = tmp_path / "postgres.dump"
    parsed_input = tmp_path / "parsed-input"
    result = subprocess.run(
        [str(binary_dir / "pg_dump"), "--format=custom", "--file", str(output)],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{binary_dir}:{os.environ['PATH']}",
            "P7_PG_SOURCE_CONTAINER": "disposable-source",
            "P7_PG_DATABASE": "fixture",
            "ARCHIVE_MODE": mode,
            "PARSED_INPUT": str(parsed_input),
        },
        capture_output=True,
        timeout=5,
    )
    assert result.returncode == expected_status
    if mode == "empty":
        assert not parsed_input.exists()
        assert b"empty archive" in result.stderr
    else:
        assert parsed_input.read_bytes() == output.read_bytes()
    assert not (tmp_path / "-").exists()


@pytest.mark.parametrize("ownership_allowed", [True, False])
def test_openbao_restore_hands_private_snapshot_to_service_user_before_restore(
    tmp_path: Path, ownership_allowed: bool
) -> None:
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    (binary_dir / "bao").symlink_to(WRAPPER)
    docker = binary_dir / "docker"
    docker.write_text(
        """#!/usr/bin/env python3
import json, os, shutil, sys
from pathlib import Path
state_file = Path(os.environ['DOCKER_STATE'])
snapshot = Path(os.environ['COPIED_SNAPSHOT'])
arguments = sys.argv[1:]
state = json.loads(state_file.read_text()) if state_file.exists() else {}
if arguments[0] == 'cp':
    shutil.copyfile(arguments[1], snapshot)
    snapshot.chmod(0o600)
    state = {'owner': 'root', 'restored': False}
elif arguments[0:3] == ['exec', '--user', '0:0']:
    assert arguments[3] == 'disposable-bao-target'
    if arguments[4:6] == ['chown', 'openbao:openbao']:
        if os.environ['OWNERSHIP_ALLOWED'] != 'yes':
            raise SystemExit(13)
        state['owner'] = 'openbao'
    elif arguments[4:6] == ['chmod', '600']:
        snapshot.chmod(0o600)
    else:
        raise SystemExit(2)
elif arguments[0] == 'exec' and 'bao' in arguments:
    # Restore must keep the default service user, never root or world-readable input.
    assert '--user' not in arguments
    assert state['owner'] == 'openbao'
    assert snapshot.stat().st_mode & 0o777 == 0o600
    assert snapshot.read_bytes() == b'private-snapshot-fixture'
    state['restored'] = True
elif arguments[0] == 'exec' and 'rm' in arguments:
    snapshot.unlink()
else:
    raise SystemExit(2)
state_file.write_text(json.dumps(state))
""",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    source = tmp_path / "source.snap"
    source.write_bytes(b"private-snapshot-fixture")
    source.chmod(0o600)
    state_file = tmp_path / "docker-state.json"
    copied = tmp_path / "container-snapshot"
    result = subprocess.run(
        [str(binary_dir / "bao"), "operator", "raft", "snapshot", "restore", "-force", str(source)],
        env={
            **os.environ,
            "PATH": f"{binary_dir}:{os.environ['PATH']}",
            "P7_OPENBAO_TARGET_CONTAINER": "disposable-bao-target",
            "P7_OPENBAO_TARGET_TOKEN": "ephemeral-test-token",
            "DOCKER_STATE": str(state_file),
            "COPIED_SNAPSHOT": str(copied),
            "OWNERSHIP_ALLOWED": "yes" if ownership_allowed else "no",
        },
        capture_output=True,
        timeout=5,
    )
    state = json.loads(state_file.read_text())
    assert result.returncode == (0 if ownership_allowed else 13)
    assert state["restored"] is ownership_allowed
    assert source.stat().st_mode & 0o777 == 0o600
    if ownership_allowed:
        assert not copied.exists()
    else:
        assert copied.stat().st_mode & 0o777 == 0o600
