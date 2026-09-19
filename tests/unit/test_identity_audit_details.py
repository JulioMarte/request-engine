import pytest

from request_engine.modules.tenancy.application.commands.identity_audit import (
    IdentityAuditAction,
    IdentityAuditDetails,
    IdentityAuditReason,
    IdentitySubjectKind,
    status_transition_reason,
)


def _details(**overrides: object) -> IdentityAuditDetails:
    values: dict[str, object] = {
        "action": IdentityAuditAction.CREDENTIAL_ROTATE,
        "reason_code": IdentityAuditReason.CREDENTIAL_ROTATED,
        "subject_kind": IdentitySubjectKind.INTEGRATION_CREDENTIAL,
        "revision_before": 3,
        "revision_after": 4,
    }
    values.update(overrides)
    return IdentityAuditDetails(**values)  # type: ignore[arg-type]


def test_credential_rotate_details_expose_no_secret_material() -> None:
    payload = _details().to_details()
    assert payload == {
        "action": "credential_rotate",
        "reason_code": "credential_rotated",
        "subject_kind": "IntegrationCredential",
        "revision_before": 3,
        "revision_after": 4,
    }
    assert "external_case_reference" not in payload


def test_external_case_reference_is_optional_and_normalized() -> None:
    details = _details(external_case_reference="  case-2026-014  ")
    assert details.to_details()["external_case_reference"] == "case-2026-014"


@pytest.mark.parametrize(
    ("revision_before", "revision_after"),
    [(-1, 0), (2, 1)],
)
def test_revisions_must_be_non_negative_and_non_decreasing(
    revision_before: int,
    revision_after: int,
) -> None:
    with pytest.raises(ValueError):
        _details(revision_before=revision_before, revision_after=revision_after)


@pytest.mark.parametrize("reference", ["x" * 401, "   ", ""])
def test_external_case_reference_is_bounded(reference: str) -> None:
    with pytest.raises(ValueError):
        _details(external_case_reference=reference)


def test_status_transition_reason_is_closed() -> None:
    assert (
        status_transition_reason(IdentitySubjectKind.STAFF_MEMBERSHIP, "suspended")
        is IdentityAuditReason.STAFF_SUSPENDED
    )
    assert (
        status_transition_reason(IdentitySubjectKind.AGENT_PRINCIPAL, "revoked")
        is IdentityAuditReason.AGENT_REVOKED
    )
    assert (
        status_transition_reason(IdentitySubjectKind.INTEGRATION_PRINCIPAL, "active")
        is IdentityAuditReason.INTEGRATION_ACTIVATED
    )
    with pytest.raises(ValueError):
        status_transition_reason(IdentitySubjectKind.INTEGRATION_CREDENTIAL, "active")
    with pytest.raises(ValueError):
        status_transition_reason(IdentitySubjectKind.STAFF_MEMBERSHIP, "deleted")


def test_policy_upgrade_details_are_optional_normalized_and_bounded() -> None:
    details = _details(
        action=IdentityAuditAction.POLICY_UPGRADE,
        reason_code=IdentityAuditReason.CONTROLLER_POLICY_UPGRADED,
        subject_kind=IdentitySubjectKind.TENANT_CONTROLLER,
        source_policy_key="  tenant-controller-v1  ",
        target_policy_key="tenant-controller-v3",
    )
    assert details.to_details() == {
        "action": "policy_upgrade",
        "reason_code": "controller_policy_upgraded",
        "subject_kind": "TenantController",
        "revision_before": 3,
        "revision_after": 4,
        "source_policy_key": "tenant-controller-v1",
        "target_policy_key": "tenant-controller-v3",
    }
    assert "source_policy_key" not in _details().to_details()
    assert "target_policy_key" not in _details().to_details()


@pytest.mark.parametrize("policy_key", ["x" * 201, "   ", ""])
def test_policy_keys_are_bounded_when_present(policy_key: str) -> None:
    with pytest.raises(ValueError):
        _details(source_policy_key=policy_key)
    with pytest.raises(ValueError):
        _details(target_policy_key=policy_key)
