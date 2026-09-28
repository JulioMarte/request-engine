from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from request_engine.modules.platform_configuration.application.configuration import (
    ConfigurationRevision,
    PlatformConfigurationForbidden,
    PlatformConfigurationInvalid,
    PlatformConfigurationNotFound,
)
from request_engine.platform.db.session import SessionFactory, platform_actor_transaction
from request_engine.platform.security.platform_context import PlatformActorContext


class PostgresProviderCandidateReader:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def get(
        self,
        actor: PlatformActorContext,
        *,
        configuration_kind: str,
        revision: int,
        capability_key: str,
    ) -> ConfigurationRevision:
        try:
            async with platform_actor_transaction(self._session_factory, actor) as session:
                row = (
                    await session.execute(
                        text(
                            "SELECT * FROM "
                            "request_platform.read_platform_provider_candidate("
                            "CAST(:kind AS text), CAST(:revision AS bigint), "
                            "CAST(:capability AS text))"
                        ),
                        {
                            "kind": configuration_kind,
                            "revision": revision,
                            "capability": capability_key,
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
            raise

        return ConfigurationRevision(
            configuration_revision_id=UUID(str(row[0])),
            configuration_kind=str(row[1]),
            provider_kind=str(row[2]),
            revision=int(row[3]),
            configuration=dict(row[4]),
            secret_binding_id=None if row[5] is None else UUID(str(row[5])),
            state=str(row[6]),
            created_by_principal_id=UUID(str(row[7])),
            created_at=row[8],
            validated_at=row[9],
            activated_at=row[10],
            disabled_at=row[11],
        )
