from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text

from request_engine.platform.db.session import SessionFactory, platform_actor_transaction
from request_engine.platform.security.platform_context import PlatformActorContext

_PROVISION_COMMAND = "platform.tenant_provisioner.provision"


class PlatformProvisioningRejected(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProvisionedPlatformPrincipal:
    principal_id: UUID
    capability_key: str = "organization.provision"
    delegable: bool = False


class PostgresPlatformTenantProvisionerWriter:
    """Persist the specialized A->B platform provisioning transition.

    The supplied SessionFactory must connect through the dedicated
    request_platform_control runtime role. The creator Principal is not a SQL
    argument; it is bound from the trusted PlatformActorContext and re-read by
    PostgreSQL together with its current authority revision and grants.
    """

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def provision(
        self,
        *,
        actor: PlatformActorContext,
        principal_id: UUID,
        external_subject: str,
        provenance_reference: str,
    ) -> ProvisionedPlatformPrincipal:
        if not actor.allows(_PROVISION_COMMAND):
            raise PlatformProvisioningRejected(
                "Platform actor lacks platform.tenant_provisioner.provision"
            )
        if not external_subject.strip():
            raise ValueError("external_subject must be nonblank")
        if not provenance_reference.strip():
            raise ValueError("provenance_reference must be nonblank")

        async with platform_actor_transaction(self._session_factory, actor) as session:
            result = await session.execute(
                text(
                    """
                    SELECT request_platform.provision_tenant_provisioner(
                        :principal_id, :external_subject, :provenance_reference
                    )
                    """
                ),
                {
                    "principal_id": str(principal_id),
                    "external_subject": external_subject,
                    "provenance_reference": provenance_reference,
                },
            )
            created = result.scalar_one()
        return ProvisionedPlatformPrincipal(principal_id=UUID(str(created)))
