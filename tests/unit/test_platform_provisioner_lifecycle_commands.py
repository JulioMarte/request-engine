from uuid import uuid4

import pytest

from request_engine.modules.tenancy.application.commands.platform_provisioner_lifecycle import (
    PlatformProvisionerLifecycleAction,
    TransitionPlatformProvisionerCommand,
)


def _command(**overrides: object) -> TransitionPlatformProvisionerCommand:
    values: dict[str, object] = {
        "principal_id": uuid4(),
        "action": PlatformProvisionerLifecycleAction.SUSPEND,
        "expected_revision": 3,
        "reason_code": "operator_suspension",
        "idempotency_key": "lifecycle-key",
    }
    values.update(overrides)
    return TransitionPlatformProvisionerCommand(**values)  # type: ignore[arg-type]


def test_lifecycle_command_normalizes_reason_and_case_reference() -> None:
    command = _command(
        reason_code="  operator_suspension  ",
        external_case_reference="  case-2026-014  ",
    )
    assert command.normalized_reason_code == "operator_suspension"
    assert command.normalized_case_reference == "case-2026-014"


def test_lifecycle_command_requires_action_specific_reason() -> None:
    with pytest.raises(ValueError):
        _command(
            action=PlatformProvisionerLifecycleAction.REVOKE, reason_code="operator_suspension"
        )
    with pytest.raises(ValueError):
        _command(
            action=PlatformProvisionerLifecycleAction.REACTIVATE, reason_code="operator_revocation"
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"expected_revision": 0},
        {"idempotency_key": "   "},
        {"reason_code": ""},
        {"external_case_reference": "x" * 201},
    ],
)
def test_lifecycle_command_rejects_invalid_input(overrides: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _command(**overrides)
