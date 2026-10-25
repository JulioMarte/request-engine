"""The dev stack's invitation mail path stays local, pinned and dev-only.

Defects these checks catch: a published port bound to every interface (the
Mailpit inbox holds live invitation links), a floating/unpinned provider image
drifting from the CI e2e platform, plain SMTP pointed at anything other than the
in-network Mailpit sink, a non-loopback HTTP acceptance URL, an unfenced worker
outside this dev compose file, and an older stack env file breaking
`status`/`down` once new required interpolations exist.
"""

import argparse
import re
import runpy
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol, cast

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
DEV_COMPOSE = ROOT / "compose.dev.yaml"
E2E_COMPOSE = ROOT / "deploy" / "reference" / "compose.e2e.yaml"


def _services(path: Path) -> dict[str, dict[str, Any]]:
    document = cast(dict[str, Any], yaml.safe_load(path.read_text(encoding="utf-8")))
    return cast(dict[str, dict[str, Any]], document["services"])


def test_every_published_port_binds_loopback_only() -> None:
    published = [
        (name, port)
        for name, service in _services(DEV_COMPOSE).items()
        for port in service.get("ports", [])
    ]
    assert ("mailpit", "127.0.0.1:${RE_DEV_MAILPIT_PORT:?}:8025") in published
    assert all(str(port).startswith("127.0.0.1:") for _, port in published), published


def test_provider_images_are_pinned_to_the_ci_e2e_versions() -> None:
    dev, e2e = _services(DEV_COMPOSE), _services(E2E_COMPOSE)
    for name in ("openbao", "mailpit"):
        image = dev[name]["image"]
        assert re.fullmatch(r"ghcr\.io/[a-z]+/[a-z]+:v?\d+\.\d+(\.\d+)?", image), image
        assert image == e2e[name]["image"]
    # Neither the secret store nor SMTP is reachable from the host.
    assert "ports" not in dev["openbao"]
    assert dev["openbao"]["networks"] == ["backend"]


def test_invitations_are_staged_by_api_and_sent_by_worker_to_mailpit_only() -> None:
    services = _services(DEV_COMPOSE)
    api, worker = services["api"]["environment"], services["worker"]["environment"]
    accept = "http://localhost:${RE_DEV_CONSOLE_PORT:?}/staff-invitations"
    for environment in (api, worker):
        assert environment["REQUEST_ENGINE_OPENBAO_ADDR"] == "http://openbao:8200"
        assert environment["REQUEST_ENGINE_OPENBAO_TOKEN"] == "${RE_DEV_OPENBAO_ROOT_TOKEN:?}"
        assert environment["REQUEST_ENGINE_STAFF_INVITATION_ACCEPT_URL"] == accept
    # HTTP never resolves SMTP; the worker owns transport.
    assert not any(key.startswith("REQUEST_ENGINE_SMTP_") for key in api)
    assert worker["REQUEST_ENGINE_SMTP_HOST"] == "mailpit"
    assert worker["REQUEST_ENGINE_SMTP_PORT"] == "1025"
    assert worker["REQUEST_ENGINE_SMTP_STARTTLS"] == "false"
    assert worker["REQUEST_ENGINE_SMTP_SSL"] == "false"
    assert "REQUEST_ENGINE_SMTP_PASSWORD" not in worker
    assert worker["REQUEST_ENGINE_OUTBOUND_FENCED"] == "false"


def test_outbound_unfencing_is_confined_to_dev_and_e2e_compose_files() -> None:
    allowed = {DEV_COMPOSE, E2E_COMPOSE}
    offenders = [
        path
        for pattern in ("deploy/**/*.y*ml", "*.y*ml")
        for path in ROOT.glob(pattern)
        if path not in allowed
        and "REQUEST_ENGINE_OUTBOUND_FENCED" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


class _Backfill(Protocol):
    def write_env(self, values: dict[str, str]) -> None: ...
    def env(self) -> dict[str, str]: ...
    def backfill(self) -> None: ...


def test_older_stack_env_gains_new_keys_without_losing_its_ports(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sys, "path", [str(ROOT / "scripts" / "dev"), *sys.path])
    namespace = runpy.run_path(str(ROOT / "scripts" / "dev" / "local_stack.py"))
    factory = cast(Callable[[argparse.Namespace], _Backfill], namespace["Stack"])
    stack = factory(argparse.Namespace(project="backfill-test", mailpit_port=58191))
    cast(Any, stack).state = tmp_path
    cast(Any, stack).env_file = tmp_path / "dev.env"
    stack.write_env({"RE_DEV_API_PORT": "58200", "RE_DEV_POSTGRES_PASSWORD": "devonlyexisting"})

    stack.backfill()

    values = stack.env()
    assert values["RE_DEV_API_PORT"] == "58200"
    assert values["RE_DEV_POSTGRES_PASSWORD"] == "devonlyexisting"
    assert values["RE_DEV_MAILPIT_PORT"] == "58191"
    assert values["RE_DEV_OPENBAO_ROOT_TOKEN"].startswith("devonly")
    assert len(values["RE_DEV_OPENBAO_ROOT_TOKEN"]) > 32
