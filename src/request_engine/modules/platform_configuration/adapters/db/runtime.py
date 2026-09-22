from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Row

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
        return _materialize(row)

    async def read_revision(
        self,
        configuration_kind: str,
        revision: int,
    ) -> ActivePlatformConfiguration | None:
        async with self._session_factory() as session, session.begin():
            row = (
                await session.execute(
                    text(
                        "SELECT * FROM "
                        "request_platform.read_platform_runtime_configuration_revision("
                        "CAST(:kind AS text), CAST(:revision AS bigint))"
                    ),
                    {"kind": configuration_kind, "revision": revision},
                )
            ).one_or_none()
        return _materialize(row)


def _materialize(row: Row[Any] | None) -> ActivePlatformConfiguration | None:
    if row is None:
        return None
    values = row
    return ActivePlatformConfiguration(
        configuration_revision_id=UUID(str(values[0])),
        configuration_kind=str(values[1]),
        provider_kind=str(values[2]),
        revision=int(values[3]),
        configuration=dict(values[4]),
        secret_binding_id=None if values[5] is None else UUID(str(values[5])),
        secret_binding_revision=None if values[6] is None else int(values[6]),
        secret_id=None if values[7] is None else UUID(str(values[7])),
        secret_purpose=None if values[8] is None else str(values[8]),
        secret_backend=None if values[9] is None else str(values[9]),
        secret_backend_version=None if values[10] is None else int(values[10]),
        secret_status=None if values[11] is None else str(values[11]),
    )
