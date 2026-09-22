from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from request_engine.modules.platform_configuration.application.configuration import (
    PlatformConfigurationForbidden,
    PlatformConfigurationInvalid,
    PlatformConfigurationNotFound,
    PlatformConfigurationRevisionConflict,
)
from request_engine.platform.db.session import SessionFactory, platform_actor_transaction
from request_engine.platform.security.platform_context import PlatformActorContext


@dataclass(frozen=True, slots=True)
class ProviderSecretReference:
    binding_id: UUID
    secret_id: UUID
    purpose: str
    backend: str
    backend_version: int
    status: str
    revision: int


class PostgresProviderSecretResolver:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def resolve(
        self,
        actor: PlatformActorContext,
        *,
        binding_id: UUID,
        capability_key: str,
    ) -> ProviderSecretReference:
        try:
            async with platform_actor_transaction(self._session_factory, actor) as session:
                row = (
                    await session.execute(
                        text(
                            "SELECT * FROM "
                            "request_platform.resolve_platform_provider_secret("
                            "CAST(:binding_id AS uuid), CAST(:capability_key AS text))"
                        ),
                        {
                            "binding_id": binding_id,
                            "capability_key": capability_key,
                        },
                    )
                ).one()
        except DBAPIError as exc:
            state = str(getattr(exc.orig, "sqlstate", ""))
            if state == "P0002":
                raise PlatformConfigurationNotFound() from None
            if state in {"42501", "28000"}:
                raise PlatformConfigurationForbidden() from None
            if state in {"22023", "23514"}:
                raise PlatformConfigurationInvalid() from None
            if state in {"40001", "40P01"}:
                raise PlatformConfigurationRevisionConflict() from None
            raise
        return ProviderSecretReference(
            binding_id=UUID(str(row[0])),
            secret_id=UUID(str(row[1])),
            purpose=str(row[2]),
            backend=str(row[3]),
            backend_version=int(row[4]),
            status=str(row[5]),
            revision=int(row[6]),
        )
