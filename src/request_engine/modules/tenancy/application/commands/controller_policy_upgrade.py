from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from request_engine.platform.security.context import ActorContext

CONTROLLER_POLICY_UPGRADE_CAPABILITY = "controller_policy_upgrade"


@dataclass(frozen=True, slots=True)
class UpgradeControllerPolicyCommand:
    target_principal_id: UUID
    source_policy_key: str
    target_policy_key: str
    expected_authority_revision: int
    idempotency_key: str


class ControllerPolicyUpgradeCommands(Protocol):
    async def upgrade_controller_policy(
        self,
        actor: ActorContext,
        command: UpgradeControllerPolicyCommand,
    ) -> int: ...
