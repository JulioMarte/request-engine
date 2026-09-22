from __future__ import annotations

from uuid import UUID

from sqlalchemy import text

from request_engine.modules.platform_configuration.application.runtime import (
    ActivePlatformConfiguration,
)
from request_engine.platform.db.session import SessionFactory


class PostgresActivePlatformConfigurationSource:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def read_active(
        self,
        configuration_kind: str,
    ) -> ActivePlatformConfiguration | None:
        async with self._session_factory() as session, session.begin():
            row = (
                await session.execute(
                    text(
                        "SELECT * FROM "
                        "request_platform.read_active_platform_runtime_configuration("
                        "CAST(:kind AS text))"
                    ),
                    {"kind": configuration_kind},
                )
            ).one_or_none()
        if row is None:
            return None
        return ActivePlatformConfiguration(
            configuration_revision_id=UUID(str(row[0])),
            configuration_kind=str(row[1]),
            provider_kind=str(row[2]),
            revision=int(row[3]),
            configuration=dict(row[4]),
            secret_binding_id=None if row[5] is None else UUID(str(row[5])),
            secret_binding_revision=None if row[6] is None else int(row[6]),
            secret_id=None if row[7] is None else UUID(str(row[7])),
            secret_purpose=None if row[8] is None else str(row[8]),
            secret_backend=None if row[9] is None else str(row[9]),
            secret_backend_version=None if row[10] is None else int(row[10]),
            secret_status=None if row[11] is None else str(row[11]),
        )
