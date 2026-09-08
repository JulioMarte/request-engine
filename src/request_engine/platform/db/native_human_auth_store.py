from datetime import datetime
from uuid import UUID

from sqlalchemy import text

from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.native_auth import OpaqueTokenMaterial
from request_engine.platform.security.native_human_auth import (
    NativeHumanAuthStore,
    NativePasswordCredentialSnapshot,
)
from request_engine.platform.security.native_session import (
    NativeCredentialStatus,
    NativeIdentityStatus,
)


class PostgresNativeHumanAuthStore(NativeHumanAuthStore):
    """Persist Native HUMAN auth through request_auth SECURITY DEFINER functions."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def read_password_credential(
        self, *, identity_authority_id: UUID, login_handle: str
    ) -> NativePasswordCredentialSnapshot | None:
        async with self._session_factory() as session, session.begin():
            row = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT native_identity_id,
                                   credential_id,
                                   verifier,
                                   identity_status,
                                   credential_status,
                                   session_epoch,
                                   identity_revision,
                                   credential_revision
                              FROM request_auth.read_native_password_credential(
                                  :identity_authority_id,
                                  :login_handle
                              )
                            """
                        ),
                        {
                            "identity_authority_id": identity_authority_id,
                            "login_handle": login_handle,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        return NativePasswordCredentialSnapshot(
            native_identity_id=UUID(str(row["native_identity_id"])),
            credential_id=UUID(str(row["credential_id"])),
            verifier=str(row["verifier"]),
            identity_status=NativeIdentityStatus(str(row["identity_status"])),
            credential_status=NativeCredentialStatus(str(row["credential_status"])),
            session_epoch=int(row["session_epoch"]),
            identity_revision=int(row["identity_revision"]),
            credential_revision=int(row["credential_revision"]),
        )

    async def create_identity(
        self,
        *,
        identity_authority_id: UUID,
        native_identity_id: UUID,
        login_handle: str,
        credential_id: UUID,
        verifier: str,
    ) -> bool:
        return await self._call_boolean(
            """
            SELECT request_auth.create_native_identity(
                :identity_authority_id,
                :native_identity_id,
                :login_handle,
                :credential_id,
                :verifier
            )
            """,
            {
                "identity_authority_id": identity_authority_id,
                "native_identity_id": native_identity_id,
                "login_handle": login_handle,
                "credential_id": credential_id,
                "verifier": verifier,
            },
        )

    async def create_session(
        self,
        *,
        native_identity_id: UUID,
        credential_id: UUID,
        token: OpaqueTokenMaterial,
        expires_at: datetime,
    ) -> bool:
        return await self._call_boolean(
            """
            SELECT request_auth.create_native_session(
                :native_identity_id,
                :credential_id,
                :session_id,
                :token_digest,
                :token_fingerprint,
                :expires_at
            )
            """,
            {
                "native_identity_id": native_identity_id,
                "credential_id": credential_id,
                "session_id": token.token_id,
                "token_digest": token.digest,
                "token_fingerprint": token.fingerprint,
                "expires_at": expires_at,
            },
        )

    async def revoke_session(
        self, *, native_identity_id: UUID, session_id: UUID, reason: str
    ) -> bool:
        return await self._call_boolean(
            "SELECT request_auth.revoke_native_session(:identity_id, :session_id, :reason)",
            {
                "identity_id": native_identity_id,
                "session_id": session_id,
                "reason": reason,
            },
        )

    async def revoke_all_sessions(self, *, native_identity_id: UUID, reason: str) -> bool:
        return await self._call_boolean(
            "SELECT request_auth.revoke_native_sessions(:identity_id, :reason)",
            {"identity_id": native_identity_id, "reason": reason},
        )

    async def rotate_password(
        self,
        *,
        native_identity_id: UUID,
        expected_credential_id: UUID,
        new_credential_id: UUID,
        new_verifier: str,
        reason: str,
    ) -> bool:
        return await self._call_boolean(
            """
            SELECT request_auth.rotate_native_password(
                :identity_id,
                :expected_credential_id,
                :new_credential_id,
                :new_verifier,
                :reason
            )
            """,
            {
                "identity_id": native_identity_id,
                "expected_credential_id": expected_credential_id,
                "new_credential_id": new_credential_id,
                "new_verifier": new_verifier,
                "reason": reason,
            },
        )

    async def disable_identity(self, *, native_identity_id: UUID, reason: str) -> bool:
        return await self._call_boolean(
            "SELECT request_auth.disable_native_identity(:identity_id, :reason)",
            {"identity_id": native_identity_id, "reason": reason},
        )

    async def create_recovery_intent(
        self,
        *,
        native_identity_id: UUID,
        token: OpaqueTokenMaterial,
        expires_at: datetime,
    ) -> bool:
        return await self._call_boolean(
            """
            SELECT request_auth.create_native_recovery_intent(
                :identity_id,
                :recovery_id,
                :token_digest,
                :token_fingerprint,
                :expires_at
            )
            """,
            {
                "identity_id": native_identity_id,
                "recovery_id": token.token_id,
                "token_digest": token.digest,
                "token_fingerprint": token.fingerprint,
                "expires_at": expires_at,
            },
        )

    async def consume_recovery_intent(
        self,
        *,
        recovery_id: UUID,
        token_digest: bytes,
        new_credential_id: UUID,
        new_verifier: str,
    ) -> UUID | None:
        async with self._session_factory() as session, session.begin():
            value = (
                await session.execute(
                    text(
                        """
                        SELECT request_auth.consume_native_recovery_intent(
                            :recovery_id,
                            :token_digest,
                            :new_credential_id,
                            :new_verifier
                        )
                        """
                    ),
                    {
                        "recovery_id": recovery_id,
                        "token_digest": token_digest,
                        "new_credential_id": new_credential_id,
                        "new_verifier": new_verifier,
                    },
                )
            ).scalar_one()
        if value is None:
            return None
        return UUID(str(value))

    async def _call_boolean(self, statement: str, parameters: dict[str, object]) -> bool:
        async with self._session_factory() as session, session.begin():
            value = (await session.execute(text(statement), parameters)).scalar_one()
        return bool(value)
