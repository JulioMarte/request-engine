"""A retired database must be refused before replacing an existing image tag."""

import argparse
import runpy
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, cast

import pytest

ROOT = Path(__file__).resolve().parents[3]


class Startup(Protocol):
    def up(self) -> None: ...


def test_unknown_lineage_refuses_before_build_or_migration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "path", [str(ROOT / "scripts" / "dev"), *sys.path])
    namespace = runpy.run_path(str(ROOT / "scripts" / "dev" / "local_stack.py"))
    factory = cast(Callable[[argparse.Namespace], Startup], namespace["Stack"])
    stack = factory(argparse.Namespace(project="startup-refusal-test"))
    calls: list[tuple[str, ...]] = []

    def configure(_self: object) -> dict[str, str]:
        return {}

    def compose(_self: object, *arguments: str) -> str:
        calls.append(arguments)
        return ""

    def reject(_self: object) -> None:
        raise SystemExit("retired lineage; preserve existing data")

    monkeypatch.setattr(type(stack), "configure", configure)
    monkeypatch.setattr(type(stack), "compose", compose)
    monkeypatch.setattr(type(stack), "require_known_revision", reject)
    with pytest.raises(SystemExit, match="preserve existing data"):
        stack.up()
    assert calls == [("up", "-d", "--wait", "postgres")]
