"""Shell-adapter regressions; PostgreSQL archive semantics run in the live lab."""

import os
import subprocess
from pathlib import Path

import pytest

WRAPPER = Path(__file__).resolve().parents[3] / "scripts/ci/p7_recovery_lab_tool.sh"


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
