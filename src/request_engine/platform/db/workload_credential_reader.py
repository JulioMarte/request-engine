from datetime import datetime
from uuid import UUID

from sqlalchemy import text

from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.workload_auth import (
    WorkloadAuthorityStatus,
    WorkloadCredentialSnapshot,
    WorkloadCredentialStatus,
    WorkloadIdentityStatus,
    WorkloadKind,
)


class PostgresWorkloadCredentialReader:
    """Read one workload credential through the narrow request_auth boundary."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def read_workload_credential(
        self, *, credential_id: UUID
    ) -> WorkloadCredentialSnapshot | None:
        async with self._session_factory() as session, session.begin():
            row = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT credential_id,
                                   workload_identity_id,
                                   identity_authority_id,
                                   workload_kind,
                                   token_digest,
                                   credential_status,
                                   identity_status,
                                   authority_status,
                                   expires_at
                              FROM request_auth.read_workload_credential(:credential_id)
                            """
                        ),
                        {"credential_id": credential_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        expires_at = row["expires_at"]
        if not isinstance(expires_at, datetime):
            raise RuntimeError("workload credential expiry could not be materialized")
        return WorkloadCredentialSnapshot(
            credential_id=UUID(str(row["credential_id"])),
            workload_identity_id=UUID(str(row["workload_identity_id"])),
            identity_authority_id=UUID(str(row["identity_authority_id"])),
            workload_kind=WorkloadKind(str(row["workload_kind"])),
            token_digest=bytes(row["token_digest"]),
            credential_status=WorkloadCredentialStatus(str(row["credential_status"])),
            identity_status=WorkloadIdentityStatus(str(row["identity_status"])),
            authority_status=WorkloadAuthorityStatus(str(row["authority_status"])),
            expires_at=expires_at,
        )
