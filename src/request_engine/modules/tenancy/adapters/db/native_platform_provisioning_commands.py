import hashlib
import json
from uuid import UUID, uuid5

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from request_engine.modules.tenancy.application.commands.native_platform_provisioning import (
    NativeOrganizationResult,
    NativePlatformProvisionerResult,
    NativePlatformProvisioningConflict,
    NativePlatformProvisioningError,
    NativePlatformProvisioningForbidden,
    NativePlatformProvisioningInvalid,
    NativePlatformProvisioningRevisionConflict,
    ProvisionNativeOrganizationCommand,
    ProvisionNativePlatformProvisionerCommand,
)
from request_engine.platform.db.session import SessionFactory, platform_actor_transaction
from request_engine.platform.security.context import PrincipalKind
from request_engine.platform.security.platform_context import PlatformActorContext

_COMMAND = "platform.tenant_provisioner.provision"
_IDENTITY_NAMESPACE = UUID("3c5d5844-f55f-4fe6-8f27-7df407fab96a")
_DATABASE_ERRORS: dict[str, type[NativePlatformProvisioningError]] = {
    "23505": NativePlatformProvisioningConflict,
    "23514": NativePlatformProvisioningInvalid,
    "22023": NativePlatformProvisioningInvalid,
    "40001": NativePlatformProvisioningRevisionConflict,
    "40P01": NativePlatformProvisioningRevisionConflict,
    "42501": NativePlatformProvisioningForbidden,
    "28000": NativePlatformProvisioningForbidden,
}


class PostgresNativePlatformProvisioningCommands:
    """One transaction through a dedicated platform-control connection.

    IDs are stable per creator/key; PostgreSQL compares all immutable payload
    fields and current authority on replay. Results never contain credentials.
    """

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def provision_native_platform_provisioner(
        self, actor: PlatformActorContext, command: ProvisionNativePlatformProvisionerCommand
    ) -> NativePlatformProvisionerResult:
        if actor.principal_kind is not PrincipalKind.HUMAN or not actor.allows(_COMMAND):
            raise NativePlatformProvisioningForbidden(_COMMAND)
        operation_id = uuid5(_IDENTITY_NAMESPACE, f"{actor.principal_id}:{command.idempotency_key}")
        principal_id = uuid5(operation_id, "principal")
        binding_id = uuid5(operation_id, "binding")
        try:
            async with platform_actor_transaction(self._session_factory, actor) as session:
                created = (
                    await session.execute(
                        text("""
                        SELECT request_platform.provision_native_tenant_provisioner(
                            :principal_id, :binding_id, :authority_id, :identity_id, :provenance
                        )
                        """),
                        {
                            "principal_id": principal_id,
                            "binding_id": binding_id,
                            "authority_id": command.identity_authority_id,
                            "identity_id": command.native_identity_id,
                            "provenance": command.provenance_reference,
                        },
                    )
                ).scalar_one()
                if UUID(str(created)) != principal_id:
                    raise RuntimeError(
                        "Native provisioner persistence returned an unexpected identity"
                    )
        except DBAPIError as exc:
            error_type = _DATABASE_ERRORS.get(str(getattr(exc.orig, "sqlstate", "")))
            if error_type is None:
                raise
            raise error_type() from None
        return NativePlatformProvisionerResult(principal_id=principal_id, binding_id=binding_id)

    async def provision_native_organization(
        self, actor: PlatformActorContext, command: ProvisionNativeOrganizationCommand
    ) -> NativeOrganizationResult:
        if actor.principal_kind is not PrincipalKind.HUMAN or not actor.allows(
            "organization.provision"
        ):
            raise NativePlatformProvisioningForbidden("organization.provision")
        operation_id = uuid5(
            _IDENTITY_NAMESPACE, f"organization:{actor.principal_id}:{command.idempotency_key}"
        )
        # Bind the immutable root fact to the entire normalized creation intent.
        # Do not compare against mutable organization fields on later replays.
        intent = {
            "organization_key": command.organization_key.strip(),
            "display_name": command.display_name.strip(),
            "authority_id": str(command.identity_authority_id),
            "identity_id": str(command.native_identity_id),
            "provenance": command.provenance_reference.strip(),
        }
        digest = hashlib.sha256(
            json.dumps(intent, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        parameters = {
            **intent,
            "organization_id": uuid5(operation_id, "organization"),
            "party_id": uuid5(operation_id, "party"),
            "principal_id": uuid5(operation_id, "controller"),
            "provenance": f"native-root-v1:{digest}:{intent['provenance']}",
        }
        try:
            async with platform_actor_transaction(self._session_factory, actor) as session:
                # The selected policy applies on INSERT only. Root replay must
                # retain its committed policy and never re-materialize grants.
                await session.execute(
                    text("SELECT request_platform.select_initial_controller_policy(:policy)"),
                    {"policy": command.initial_controller_policy},
                )
                row = (
                    await session.execute(
                        text("""
                        SELECT * FROM request_platform.provision_native_organization_root(
                            :organization_id, :organization_key, :display_name, :party_id,
                            :principal_id, :authority_id, :identity_id, :provenance
                        )
                        """),
                        parameters,
                    )
                ).one()
                return NativeOrganizationResult(
                    organization_id=UUID(str(row[0])),
                    organization_party_id=UUID(str(row[1])),
                    controller_principal_id=UUID(str(row[2])),
                    controller_binding_id=UUID(str(row[3])),
                )
        except DBAPIError as exc:
            error_type = _DATABASE_ERRORS.get(str(getattr(exc.orig, "sqlstate", "")))
            if error_type is None:
                raise
            raise error_type() from None
