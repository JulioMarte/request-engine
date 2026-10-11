from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/ci/run_e2e_suite.sh"


@pytest.mark.parametrize("cached", [False, True])
def test_optional_provider_is_built_even_when_its_tag_already_exists(
    tmp_path: Path, cached: bool
) -> None:
    # The Docker boundary is excluded here. Verify the actual shell launcher
    # requests a build; live container execution belongs to Docker E2E CI.
    result, calls = _run_builder(
        tmp_path,
        {"provider": {"build": {"context": "."}}, "gateway": {"image": "nginx"}},
        cached=cached,
    )
    assert result.returncode == 0, result.stderr
    assert calls == ["config --format json", "build provider"]


def test_external_image_is_not_rebuilt(tmp_path: Path) -> None:
    result, calls = _run_builder(
        tmp_path, {"provider": {"image": "external"}, "gateway": {"image": "nginx"}}
    )
    assert result.returncode == 0, result.stderr
    assert calls == ["config --format json"]


def test_missing_declared_provider_fails_closed(tmp_path: Path) -> None:
    result, calls = _run_builder(tmp_path, {"gateway": {"image": "nginx"}})
    assert result.returncode != 0
    assert "missing from topology" in result.stderr
    assert calls == ["config --format json"]


def _run_builder(
    root: Path, services: dict[str, object], *, cached: bool = False
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    topology = root / "topology.json"
    topology.write_text(json.dumps({"services": services}), encoding="utf-8")
    call_log = root / "calls.txt"
    fake_docker = root / "docker"
    fake_docker.write_text(
        '#!/bin/bash\nset -eu\nprintf "%s\\n" "$*" >> "$CALL_LOG"\n'
        'if [[ "$1" == config ]]; then cat "$TOPOLOGY"; fi\n',
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)
    # Source the real definitions without starting a deployment. Give them a
    # recording Docker boundary and retain Bash errexit/pipefail semantics.
    definitions = SCRIPT.read_text(encoding="utf-8").split('[[ "$requested" != "all" ]]')[0]
    invocation = (
        definitions
        + "\n"
        + "\n".join(
            (
                'compose=("$FAKE_DOCKER")',
                "declared_infrastructure=(provider)",
                "ingress_services=(gateway)",
                'suite_artifacts="$TEST_ROOT"',
                'retry_docker() { shift; "$@"; }',
                "build_infrastructure_images",
            )
        )
    )
    result = subprocess.run(
        ["bash", "-c", invocation],
        cwd=ROOT,
        env={
            **os.environ,
            "CALL_LOG": str(call_log),
            "TOPOLOGY": str(topology),
            "FAKE_DOCKER": str(fake_docker),
            "TEST_ROOT": str(root),
            "E2E_IMAGES_READY": "1" if cached else "0",
        },
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result, call_log.read_text(encoding="utf-8").splitlines()
