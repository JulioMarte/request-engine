"""Least-privilege WebAuthn credential/challenge persistence (ADR 0014 §5.5).

The runtime app login reaches WebAuthn state only through the narrow
``request_auth`` functions; it has no direct table authority. Public credential
material crosses this boundary, never an authenticator private key.

Challenge finalization is coupled to its authoritative consequence in a single
``request_auth`` transaction: verification happens in Python outside any lock and
only the trusted finalization consumes the challenge while writing the credential,
session or step-up fact.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text

from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.native_webauthn_auth import (
    WebAuthnChallengeScope,
    WebAuthnCredentialRecord,
)


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

    async def read_challenge(
        self, *, challenge_digest: bytes, purpose: str
    ) -> WebAuthnChallengeScope | None:
        async with self._session_factory() as session, session.begin():
            row = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT native_identity_id, session_id, setup_session_id, expires_at
                              FROM request_auth.read_webauthn_challenge(
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
        return WebAuthnChallengeScope(
            native_identity_id=_uuid_or_none(row["native_identity_id"]),
            session_id=_uuid_or_none(row["session_id"]),
            setup_session_id=_uuid_or_none(row["setup_session_id"]),
            expires_at=_timestamp(row["expires_at"], "challenge expiry"),
        )

    async def read_credential(self, *, credential_id: bytes) -> WebAuthnCredentialRecord | None:
        async with self._session_factory() as session, session.begin():
            row = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT id, native_identity_id, credential_id, public_key,
                                   sign_count, aaguid, backup_eligible, backup_state,
                                   user_verified, status
                              FROM request_auth.read_webauthn_credential(:credential_id)
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
        return _record(dict(row))

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
            _record({**dict(row), "native_identity_id": native_identity_id}) for row in rows
        )

    async def finalize_registration(
        self,
        *,
        challenge_digest: bytes,
        credential_row_id: UUID,
        credential_id: bytes,
        public_key: bytes,
        sign_count: int,
        aaguid: str,
        backup_eligible: bool,
        backup_state: bool,
        user_verified: bool,
    ) -> bool:
        async with self._session_factory() as session, session.begin():
            value = await session.scalar(
                text(
                    """
                    SELECT request_auth.finalize_webauthn_registration(
                        :challenge_digest, :credential_row_id, :credential_id,
                        :public_key, :sign_count, :aaguid, :backup_eligible,
                        :backup_state, :user_verified
                    )
                    """
                ),
                {
                    "challenge_digest": challenge_digest,
                    "credential_row_id": credential_row_id,
                    "credential_id": credential_id,
                    "public_key": public_key,
                    "sign_count": sign_count,
                    "aaguid": aaguid,
                    "backup_eligible": backup_eligible,
                    "backup_state": backup_state,
                    "user_verified": user_verified,
                },
            )
        return value is True

    async def finalize_authentication(
        self,
        *,
        challenge_digest: bytes,
        credential_row_id: UUID,
        native_identity_id: UUID,
        sign_count: int,
        backup_eligible: bool,
        backup_state: bool,
        user_verified: bool,
        session_id: UUID,
        token_digest: bytes,
        token_fingerprint: str,
        expires_at: datetime,
    ) -> bool:
        async with self._session_factory() as session, session.begin():
            value = await session.scalar(
                text(
                    """
                    SELECT request_auth.finalize_webauthn_authentication(
                        :challenge_digest, :credential_row_id, :native_identity_id,
                        :sign_count, :backup_eligible, :backup_state, :user_verified,
                        :session_id, :token_digest, :token_fingerprint, :expires_at
                    )
                    """
                ),
                {
                    "challenge_digest": challenge_digest,
                    "credential_row_id": credential_row_id,
                    "native_identity_id": native_identity_id,
                    "sign_count": sign_count,
                    "backup_eligible": backup_eligible,
                    "backup_state": backup_state,
                    "user_verified": user_verified,
                    "session_id": session_id,
                    "token_digest": token_digest,
                    "token_fingerprint": token_fingerprint,
                    "expires_at": expires_at,
                },
            )
        return value is True

    async def finalize_step_up(
        self,
        *,
        challenge_digest: bytes,
        credential_row_id: UUID,
        session_id: UUID,
        native_identity_id: UUID,
        sign_count: int,
        backup_eligible: bool,
        user_verified: bool,
    ) -> bool:
        async with self._session_factory() as session, session.begin():
            value = await session.scalar(
                text(
                    """
                    SELECT request_auth.finalize_webauthn_step_up(
                        :challenge_digest, :credential_row_id, :session_id,
                        :native_identity_id, :sign_count, :backup_eligible,
                        :user_verified
                    )
                    """
                ),
                {
                    "challenge_digest": challenge_digest,
                    "credential_row_id": credential_row_id,
                    "session_id": session_id,
                    "native_identity_id": native_identity_id,
                    "sign_count": sign_count,
                    "backup_eligible": backup_eligible,
                    "user_verified": user_verified,
                },
            )
        return value is True

    async def finalize_setup_registration(
        self,
        *,
        challenge_digest: bytes,
        credential_row_id: UUID,
        credential_id: bytes,
        public_key: bytes,
        sign_count: int,
        aaguid: str,
        backup_eligible: bool,
        backup_state: bool,
        user_verified: bool,
        setup_session_id: UUID,
    ) -> bool:
        async with self._session_factory() as session, session.begin():
            value = await session.scalar(
                text(
                    """
                    SELECT request_auth.finalize_setup_webauthn_registration(
                        :challenge_digest, :credential_row_id, :credential_id,
                        :public_key, :sign_count, :aaguid, :backup_eligible,
                        :backup_state, :user_verified, :setup_session_id
                    )
                    """
                ),
                {
                    "challenge_digest": challenge_digest,
                    "credential_row_id": credential_row_id,
                    "credential_id": credential_id,
                    "public_key": public_key,
                    "sign_count": sign_count,
                    "aaguid": aaguid,
                    "backup_eligible": backup_eligible,
                    "backup_state": backup_state,
                    "user_verified": user_verified,
                    "setup_session_id": setup_session_id,
                },
            )
        return value is True

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


def _record(row: Mapping[str, Any]) -> WebAuthnCredentialRecord:
    return WebAuthnCredentialRecord(
        id=UUID(str(row["id"])),
        native_identity_id=UUID(str(row["native_identity_id"])),
        credential_id=bytes(row["credential_id"]),  # type: ignore[arg-type]
        public_key=bytes(row["public_key"]),  # type: ignore[arg-type]
        sign_count=int(row["sign_count"]),  # type: ignore[arg-type]
        aaguid=str(row["aaguid"]),
        backup_eligible=bool(row["backup_eligible"]),
        backup_state=bool(row["backup_state"]),
        user_verified=bool(row["user_verified"]),
        status=str(row["status"]),
    )


def _timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, datetime):
        raise RuntimeError(f"WebAuthn {label} could not be materialized")
    return value


def _uuid_or_none(value: object) -> UUID | None:
    if value is None:
        return None
    return UUID(str(value))
