from __future__ import annotations

import tomllib
from pathlib import Path

from request_engine.modules.booking.contracts import capabilities as booking_capabilities

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "docs" / "v3" / "capability-manifest.toml"
BASELINE_OWNERS = {"tenancy", "catalog", "requests", "booking", "queue", "communications"}
SEMANTICS = {"query", "command", "request", "scheduled_action"}
STATUSES = {"implemented", "contract", "internal"}

# These operations exercise coordination concepts expensive enough that a production
# baseline must not freeze them as documentation-only hypotheses.
FREEZE_CRITICAL = {
    "appointments.book",
    "appointments.cancel",
    "appointments.reschedule",
    "queue.join",
    "queue.call_next",
    "waitlist.join",
    "waitlist.accept_offer",
    "waitlist.decline_offer",
    "waitlist.expire_offer",
    "requests.submit",
    "communications.create_task",
    "reminders.create_plan",
}


def _manifest() -> dict[str, object]:
    with MANIFEST.open("rb") as file:
        return tomllib.load(file)


def _capabilities() -> list[dict[str, object]]:
    raw = _manifest().get("capability")
    assert isinstance(raw, list), "capability manifest must contain [[capability]] entries"
    return raw


def test_capability_manifest_has_unique_stable_ids_and_known_owners() -> None:
    capabilities = _capabilities()
    ids = [item["id"] for item in capabilities]

    assert len(ids) == len(set(ids)), "capability ids are public identities and must be unique"
    for item in capabilities:
        assert item["owner"] in BASELINE_OWNERS
        assert item["semantic"] in SEMANTICS
        assert item["status"] in STATUSES
        assert isinstance(item["permission"], str) and item["permission"]
        assert isinstance(item["external_io_in_transaction"], bool)
        assert item["external_io_in_transaction"] is False, (
            f"{item['id']} declares external I/O inside an authoritative transaction"
        )


def test_booking_runtime_contract_uses_normative_public_capability_ids() -> None:
    manifest_ids = {item["id"] for item in _capabilities()}
    expected = {
        booking_capabilities.FIND_SLOTS,
        booking_capabilities.HOLD,
        booking_capabilities.BOOK,
        booking_capabilities.GET,
        booking_capabilities.CANCEL,
        booking_capabilities.RESCHEDULE,
        booking_capabilities.CONFIRM_ATTENDANCE,
    }

    assert expected <= manifest_ids
    assert booking_capabilities.BOOK == "appointments.book"
    assert booking_capabilities.CANCEL == "appointments.cancel"
    assert booking_capabilities.RESCHEDULE == "appointments.reschedule"


def test_schema_freeze_cannot_be_declared_while_critical_verticals_are_contract_only() -> None:
    manifest = _manifest()
    by_id = {item["id"]: item for item in _capabilities()}
    missing = FREEZE_CRITICAL - set(by_id)
    assert not missing, f"freeze-critical capabilities missing from manifest: {sorted(missing)}"

    contract_only = {
        capability_id
        for capability_id in FREEZE_CRITICAL
        if by_id[capability_id]["status"] != "implemented"
    }

    if manifest.get("freeze_ready") is True:
        assert not contract_only, (
            "schema freeze was declared before critical vertical proof exists: "
            f"{sorted(contract_only)}"
        )
    else:
        # Today this assertion protects an intentional architectural fact: the V3
        # candidate is executable design work, not production Alembic history.
        assert contract_only, (
            "all freeze-critical verticals appear implemented; re-run the full "
            "adversarial/race review before changing freeze_ready"
        )
