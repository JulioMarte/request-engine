"""Mail-link parsing proof only; real delivery/authority belong to Docker acceptance."""

import runpy
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = [pytest.mark.unit, pytest.mark.contract]


def _parser():
    with patch.object(sys, "path", [str(ROOT / "tests/fixtures"), *sys.path]):
        return runpy.run_path(str(ROOT / "tests/system_e2e/runner.py"))["_invitation_mail_proof"]


def test_invitation_mail_parser_accepts_only_matching_fragment_proof() -> None:
    parser = _parser()
    assert (
        parser(
            "https://admin.example.test/staff-invitations/other/accept#token=other.proof",
            "intended",
        )
        is None
    )
    assert (
        parser(
            "Open this link:\nhttps://admin.example.test/staff-invitations/intended/accept#token=intended.proof",
            "intended",
        )
        == "intended.proof"
    )


@pytest.mark.parametrize(
    "link",
    [
        "http://admin.example.test/staff-invitations/intended/accept#token=intended.proof",
        "https://untrusted.test/staff-invitations/intended/accept#token=intended.proof",
        "https://admin.example.test/staff-invitations/intended/accept?token=intended.proof",
        "https://admin.example.test/staff-invitations/intended/accept#token=other.proof",
        "https://admin.example.test/staff-invitations/intended/accept#token=intended.a&token=intended.b",
    ],
)
def test_invitation_mail_parser_rejects_unsafe_link_without_echoing_proof(link: str) -> None:
    with pytest.raises(RuntimeError) as error:
        _parser()(link, "intended")
    assert "intended." not in str(error.value)
    assert "other.proof" not in str(error.value)
    assert link not in str(error.value)
