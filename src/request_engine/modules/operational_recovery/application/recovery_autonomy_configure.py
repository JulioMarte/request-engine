from collections.abc import Mapping
from typing import cast
from uuid import UUID

from request_engine.modules.operational_recovery.application.recovery_autonomy_policy import (
    ConfigureRecoveryAutonomyCommand,
    RecoveryAutonomyPolicy,
)
from request_engine.platform.idempotency.postgres import command_fingerprint

CONFIGURE_CAPABILITY = "operational_recovery.configure_autonomy"


def configure_fingerprint(command: ConfigureRecoveryAutonomyCommand) -> str:
    return command_fingerprint(
        CONFIGURE_CAPABILITY,
        {
            "service_queue_id": str(command.service_queue_id),
            "enabled": command.enabled,
            "max_delay_minutes": command.max_delay_minutes,
            "max_auto_actions_per_incident": command.max_auto_actions_per_incident,
        },
    )


def policy_result(policy: RecoveryAutonomyPolicy) -> dict[str, object]:
    return {
        "organization_id": str(policy.organization_id),
        "service_queue_id": str(policy.service_queue_id),
        "enabled": policy.enabled,
        "max_delay_minutes": policy.max_delay_minutes,
        "max_auto_actions_per_incident": policy.max_auto_actions_per_incident,
        "granted_by": str(policy.granted_by),
    }


def policy_from_result(data: Mapping[str, object]) -> RecoveryAutonomyPolicy:
    return RecoveryAutonomyPolicy(
        organization_id=UUID(cast(str, data["organization_id"])),
        service_queue_id=UUID(cast(str, data["service_queue_id"])),
        enabled=cast(bool, data["enabled"]),
        max_delay_minutes=cast(int, data["max_delay_minutes"]),
        max_auto_actions_per_incident=cast(int, data["max_auto_actions_per_incident"]),
        granted_by=UUID(cast(str, data["granted_by"])),
    )
