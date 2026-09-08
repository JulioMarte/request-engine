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
        return tuple(_materialize_binding(row) for row in rows)

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
        return tuple(_materialize_binding(row, id_key="binding_id") for row in rows)


def _materialize_binding(
    row: object,
    *,
    id_key: str = "id",
) -> IdentityBindingSnapshot:
    mapping = row
    if not hasattr(mapping, "__getitem__"):
        raise RuntimeError("identity binding row is not mapping-like")
    organization_value = mapping["organization_id"]  # type: ignore[index]
    return IdentityBindingSnapshot(
        binding_id=UUID(str(mapping[id_key])),  # type: ignore[index]
        identity_authority_id=UUID(str(mapping["identity_authority_id"])),  # type: ignore[index]
        subject_id=str(mapping["subject_id"]),  # type: ignore[index]
        principal_id=UUID(str(mapping["principal_id"])),  # type: ignore[index]
        principal_plane=IdentityBindingPlane(str(mapping["principal_plane"])),  # type: ignore[index]
        organization_id=None if organization_value is None else UUID(str(organization_value)),
        status=IdentityBindingStatus(str(mapping["status"])),  # type: ignore[index]
        revision=int(mapping["revision"]),  # type: ignore[index]
    )
