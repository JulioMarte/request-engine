import pytest

from request_engine.modules.tenancy.adapters.db.staff_membership_commands import (
    _validate_provenance_reference,
    _validate_tenant_control_capabilities,
)


def test_staff_authority_validation_accepts_only_canonical_tenant_control_keys() -> None:
    assert _validate_tenant_control_capabilities(("staff.invite", "staff.manage_authority")) == (
        "staff.invite",
        "staff.manage_authority",
    )

    with pytest.raises(ValueError, match="not tenant-control"):
        _validate_tenant_control_capabilities(("appointments.cancel",))

    with pytest.raises(ValueError, match="unknown or non-canonical"):
        _validate_tenant_control_capabilities(("future.staff.superuser",))

    with pytest.raises(ValueError, match="duplicates"):
        _validate_tenant_control_capabilities(("staff.invite", "staff.invite"))


def test_staff_provenance_is_trimmed_and_bounded() -> None:
    assert _validate_provenance_reference("  invite:abc  ") == "invite:abc"

    with pytest.raises(ValueError, match="between 1 and 500"):
        _validate_provenance_reference("   ")

    with pytest.raises(ValueError, match="between 1 and 500"):
        _validate_provenance_reference("x" * 501)
