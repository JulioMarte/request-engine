from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy import text

from request_engine.platform.db.session import SessionFactory, set_tenant_context
from request_engine.platform.security.identity_resolution import (
    IdentityBindingPlane,
    IdentityBindingReader,
    IdentityBindingSnapshot,
    IdentityBindingStatus,
)


class PostgresIdentityBindingReader(IdentityBindingReader):
    """Resolve IdentityBindings without ever widening the active trust plane."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def read_tenant_subject_bindings(
        self,
        *,
        identity_authority_id: UUID,
        subject_id: str,
        organization_id: UUID,
    ) -> tuple[IdentityBindingSnapshot, ...]:
        async with self._session_factory() as session, session.begin():
            await set_tenant_context(session, organization_id)
            rows = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT id,
                                   identity_authority_id,
                                   subject_id,
                                   principal_id,
                                   principal_plane,
                                   organization_id,
                                   status,
                                   revision
                              FROM request_engine.identity_bindings
                             WHERE identity_authority_id = :identity_authority_id
                               AND subject_id = :subject_id
                               AND organization_id = :organization_id
                               AND principal_plane = 'tenant'
                            """
                        ),
                        {
                            "identity_authority_id": identity_authority_id,
                            "subject_id": subject_id,
                            "organization_id": organization_id,
                        },
                    )
                )
                .mappings()
                .all()
            )
        return tuple(_materialize_binding(dict(row)) for row in rows)

    async def read_platform_subject_bindings(
        self, *, identity_authority_id: UUID, subject_id: str
    ) -> tuple[IdentityBindingSnapshot, ...]:
        async with self._session_factory() as session, session.begin():
            rows = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT binding_id,
                                   identity_authority_id,
                                   subject_id,
                                   principal_id,
                                   principal_plane,
                                   organization_id,
                                   status,
                                   revision
                              FROM request_auth.read_platform_identity_bindings(
                                  :identity_authority_id,
                                  :subject_id
                              )
                            """
                        ),
                        {
                            "identity_authority_id": identity_authority_id,
                            "subject_id": subject_id,
                        },
                    )
                )
                .mappings()
                .all()
            )
        return tuple(_materialize_binding(dict(row), id_key="binding_id") for row in rows)


def _materialize_binding(
    row: Mapping[str, Any],
    *,
    id_key: str = "id",
) -> IdentityBindingSnapshot:
    organization_value = row["organization_id"]
    return IdentityBindingSnapshot(
        binding_id=UUID(str(row[id_key])),
        identity_authority_id=UUID(str(row["identity_authority_id"])),
        subject_id=str(row["subject_id"]),
        principal_id=UUID(str(row["principal_id"])),
        principal_plane=IdentityBindingPlane(str(row["principal_plane"])),
        organization_id=None if organization_value is None else UUID(str(organization_value)),
        status=IdentityBindingStatus(str(row["status"])),
        revision=int(row["revision"]),
    )
