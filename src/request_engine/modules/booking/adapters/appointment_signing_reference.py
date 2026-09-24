from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Row

from request_engine.platform.db.session import SessionFactory


@dataclass(frozen=True, slots=True)
class ActiveAppointmentSigningReference:
    configuration_revision: int
    secret_binding_revision: int
    secret_id: UUID
    secret_backend_version: int

    @property
    def fingerprint(self) -> tuple[int, int, int]:
        return (
            self.configuration_revision,
            self.secret_binding_revision,
            self.secret_backend_version,
        )


class PostgresAppointmentSigningReferenceSource:
    """Read the single narrow runtime projection granted to request_engine_app."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def read_active(self) -> ActiveAppointmentSigningReference | None:
        async with self._session_factory() as session, session.begin():
            row = (
                await session.execute(
                    text(
                        "SELECT * FROM "
                        "request_platform.read_active_appointment_option_signing_keyring()"
                    )
                )
            ).one_or_none()
        return _materialize(row)


def _materialize(row: Row[Any] | None) -> ActiveAppointmentSigningReference | None:
    if row is None:
        return None
    return ActiveAppointmentSigningReference(
        configuration_revision=int(row[0]),
        secret_binding_revision=int(row[1]),
        secret_id=UUID(str(row[2])),
        secret_backend_version=int(row[3]),
    )
