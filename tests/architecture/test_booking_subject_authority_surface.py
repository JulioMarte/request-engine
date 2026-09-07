from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BOOKING_ROOT = REPO_ROOT / "src" / "request_engine" / "modules" / "booking"


def test_booking_http_propagates_explicit_subject_override_permission() -> None:
    router = (BOOKING_ROOT / "api" / "router.py").read_text(encoding="utf-8")
    assert 'SUBJECT_OVERRIDE_PERMISSION = "appointments.subject_override"' not in router
    assert router.count("actor.allows(SUBJECT_OVERRIDE_PERMISSION)") >= 4


def test_authoritative_booking_mutations_resolve_subject_authority_in_transaction() -> None:
    reservation_commands = (BOOKING_ROOT / "adapters" / "db" / "reservation_commands.py").read_text(
        encoding="utf-8"
    )
    contextual_commands = (
        BOOKING_ROOT / "adapters" / "db" / "contextual_reservation_commands.py"
    ).read_text(encoding="utf-8")
    commitment_commands = (BOOKING_ROOT / "adapters" / "db" / "commitment_commands.py").read_text(
        encoding="utf-8"
    )

    booking_writers = reservation_commands + contextual_commands
    assert booking_writers.count("require_subject_authority(") >= 2
    assert commitment_commands.count("require_subject_authority(") >= 1
    assert '"subject_authority": authority.audit_details()' in booking_writers
    assert '"subject_authority": authority.audit_details()' in commitment_commands
