from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from request_engine.modules.platform_configuration.application.configuration import (
    PlatformConfigurationForbidden,
)
from request_engine.modules.platform_configuration.application.readiness import (
    PlatformReadiness,
)
from request_engine.platform.db.session import SessionFactory, platform_actor_transaction
from request_engine.platform.security.context import PrincipalKind
from request_engine.platform.security.platform_context import PlatformActorContext


class PostgresPlatformReadinessReader:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def read(self, actor: PlatformActorContext) -> PlatformReadiness:
        if actor.principal_kind is not PrincipalKind.HUMAN or not actor.allows(
            "platform.readiness.read"
        ):
            raise PlatformConfigurationForbidden("platform.readiness.read")

        try:
            async with platform_actor_transaction(self._session_factory, actor) as session:
                row = (
                    await session.execute(
                        text("SELECT * FROM request_platform.read_platform_readiness()")
                    )
                ).one()
        except DBAPIError as exc:
            if str(getattr(exc.orig, "sqlstate", "")) in {"42501", "28000"}:
                raise PlatformConfigurationForbidden("platform.readiness.read") from None
            raise

        return PlatformReadiness(
            managed_smtp_source=str(row[0]),
            smtp_active_revision=None if row[1] is None else int(row[1]),
            smtp_last_validated_at=row[2],
            smtp_last_provider_test_outcome=None if row[3] is None else str(row[3]),
            smtp_last_provider_test_at=row[4],
            smtp_secret_configured=bool(row[5]),
            oidc=str(row[6]),
        )
