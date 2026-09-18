"""Least-privilege WebAuthn credential/challenge persistence (ADR 0014 §5.5).

The runtime app login reaches WebAuthn state only through the narrow
``request_auth`` functions; it has no direct table authority. Public credential
material crosses this boundary, never an authenticator private key.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import text

from request_engine.platform.db.session import SessionFactory


@dataclass(frozen=True, slots=True)
class WebAuthnChallengeScope:
    native_identity_id: UUID | None
    session_id: UUID | None
    setup_session_id: UUID | None
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class WebAuthnCredentialRecord:
    id: UUID
    credential_id: bytes
    public_key: bytes
    sign_count: int
    aaguid: str
    backup_eligible: bool
    backup_state: bool
    user_verified: bool
    status: str


class PostgresWebAuthnStore:
    """Store and consume WebAuthn credentials/challenges through ``request_auth``."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def create_challenge(
        self,
        *,
        challenge_id: UUID,
        purpose: str,
        challenge_digest: bytes,
        expires_at: datetime,
        native_identity_id: UUID | None = None,
        session_id: UUID | None = None,
        setup_session_id: UUID | None = None,
    ) -> bool:
        async with self._session_factory() as session, session.begin():
            created = await session.scalar(
                text(
                    """
                    SELECT request_auth.create_webauthn_challenge(
                        :challenge_id, :purpose, :native_identity_id, :session_id,
                        :setup_session_id, :challenge_digest, :expires_at
                    )
                    """
                ),
                {
                    "challenge_id": challenge_id,
                    "purpose": purpose,
                    "native_identity_id": native_identity_id,
                    "session_id": session_id,
                    "setup_session_id": setup_session_id,
                    "challenge_digest": challenge_digest,
                    "expires_at": expires_at,
                },
            )
        return created is True

    async def consume_challenge(
        self, *, challenge_digest: bytes, purpose: str
    ) -> WebAuthnChallengeScope | None:
        async with self._session_factory() as session, session.begin():
            row = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT native_identity_id, session_id, setup_session_id, expires_at
                              FROM request_auth.consume_webauthn_challenge(
                                  :challenge_digest, :purpose
                              )
                            """
                        ),
                        {"challenge_digest": challenge_digest, "purpose": purpose},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        expires_at = row["expires_at"]
        if not isinstance(expires_at, datetime):
            raise RuntimeError("WebAuthn challenge expiry could not be materialized")
        return WebAuthnChallengeScope(
            native_identity_id=_uuid_or_none(row["native_identity_id"]),
            session_id=_uuid_or_none(row["session_id"]),
            setup_session_id=_uuid_or_none(row["setup_session_id"]),
            expires_at=expires_at,
        )

    async def register_credential(
        self,
        *,
        credential_row_id: UUID,
        native_identity_id: UUID,
        credential_id: bytes,
        public_key: bytes,
        sign_count: int,
        aaguid: str,
        backup_eligible: bool,
        backup_state: bool,
        user_verified: bool,
    ) -> bool:
        async with self._session_factory() as session, session.begin():
            registered = await session.scalar(
                text(
                    """
                    SELECT request_auth.register_webauthn_credential(
                        :credential_row_id, :native_identity_id, :credential_id,
                        :public_key, :sign_count, :aaguid, :backup_eligible,
                        :backup_state, :user_verified
                    )
                    """
                ),
                {
                    "credential_row_id": credential_row_id,
                    "native_identity_id": native_identity_id,
                    "credential_id": credential_id,
                    "public_key": public_key,
                    "sign_count": sign_count,
                    "aaguid": aaguid,
                    "backup_eligible": backup_eligible,
                    "backup_state": backup_state,
                    "user_verified": user_verified,
                },
            )
        return registered is True

    async def read_credentials(
        self, *, native_identity_id: UUID
    ) -> tuple[WebAuthnCredentialRecord, ...]:
        async with self._session_factory() as session, session.begin():
            rows = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT id, credential_id, public_key, sign_count, aaguid,
                                   backup_eligible, backup_state, user_verified, status
                              FROM request_auth.read_webauthn_credentials(
                                  :native_identity_id
                              )
                            """
                        ),
                        {"native_identity_id": native_identity_id},
                    )
                )
                .mappings()
                .all()
            )
        return tuple(
            WebAuthnCredentialRecord(
                id=UUID(str(row["id"])),
                credential_id=bytes(row["credential_id"]),
                public_key=bytes(row["public_key"]),
                sign_count=int(row["sign_count"]),
                aaguid=str(row["aaguid"]),
                backup_eligible=bool(row["backup_eligible"]),
                backup_state=bool(row["backup_state"]),
                user_verified=bool(row["user_verified"]),
                status=str(row["status"]),
            )
            for row in rows
        )

    async def update_sign_count(
        self,
        *,
        credential_row_id: UUID,
        native_identity_id: UUID,
        new_sign_count: int,
    ) -> bool:
        async with self._session_factory() as session, session.begin():
            updated = await session.scalar(
                text(
                    """
                    SELECT request_auth.update_webauthn_credential_sign_count(
                        :credential_row_id, :native_identity_id, :new_sign_count
                    )
                    """
                ),
                {
                    "credential_row_id": credential_row_id,
                    "native_identity_id": native_identity_id,
                    "new_sign_count": new_sign_count,
                },
            )
        return updated is True

    async def revoke_credential(
        self,
        *,
        credential_row_id: UUID,
        native_identity_id: UUID,
        reason: str,
    ) -> bool:
        async with self._session_factory() as session, session.begin():
            revoked = await session.scalar(
                text(
                    """
                    SELECT request_auth.revoke_webauthn_credential(
                        :credential_row_id, :native_identity_id, :reason
                    )
                    """
                ),
                {
                    "credential_row_id": credential_row_id,
                    "native_identity_id": native_identity_id,
                    "reason": reason,
                },
            )
        return revoked is True


def _uuid_or_none(value: object) -> UUID | None:
    if value is None:
        return None
    return UUID(str(value))
