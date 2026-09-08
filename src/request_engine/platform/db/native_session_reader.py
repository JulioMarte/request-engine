from datetime import datetime
from uuid import UUID

from sqlalchemy import text

from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.native_session import (
    NativeCredentialStatus,
    NativeIdentityStatus,
    NativeSessionSnapshot,
    NativeSessionStatus,
)


class PostgresNativeSessionReader:
    """Read exactly one Native session via the least-privilege auth boundary."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def read_native_session(self, *, session_id: UUID) -> NativeSessionSnapshot | None:
        async with self._session_factory() as session, session.begin():
            row = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT session_id,
                                   native_identity_id,
                                   identity_authority_id,
                                   credential_id,
                                   token_digest,
                                   session_epoch,
                                   current_session_epoch,
                                   session_status,
                                   identity_status,
                                   credential_status,
                                   expires_at
                              FROM request_auth.read_native_session(:session_id)
                            """
                        ),
                        {"session_id": session_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        expires_at = row["expires_at"]
        if not isinstance(expires_at, datetime):
            raise RuntimeError("native session expiry could not be materialized")
        return NativeSessionSnapshot(
            session_id=UUID(str(row["session_id"])),
            native_identity_id=UUID(str(row["native_identity_id"])),
            identity_authority_id=UUID(str(row["identity_authority_id"])),
            credential_id=UUID(str(row["credential_id"])),
            token_digest=bytes(row["token_digest"]),
            session_epoch=int(row["session_epoch"]),
            current_session_epoch=int(row["current_session_epoch"]),
            session_status=NativeSessionStatus(str(row["session_status"])),
            identity_status=NativeIdentityStatus(str(row["identity_status"])),
            credential_status=NativeCredentialStatus(str(row["credential_status"])),
            expires_at=expires_at,
        )
