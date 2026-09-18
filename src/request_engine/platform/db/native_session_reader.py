from datetime import datetime
from uuid import UUID

from sqlalchemy import text

from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.assurance import AuthenticationAssurance
from request_engine.platform.security.native_session import (
    NativeCredentialStatus,
    NativeIdentityAuthorityStatus,
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
                                   password_credential_id,
                                   password_credential_status,
                                   webauthn_credential_id,
                                   webauthn_credential_status,
                                   token_digest,
                                   session_epoch,
                                   current_session_epoch,
                                   session_status,
                                   identity_status,
                                   authority_status,
                                   authentication_methods,
                                   authentication_assurance,
                                   user_verified,
                                   recovery_derived,
                                   expires_at,
                                   created_at,
                                   last_seen_at,
                                   last_authenticated_at
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
        expires_at = _timestamp(row["expires_at"], "expiry")
        created_at = _timestamp(row["created_at"], "creation")
        authenticated_at = _timestamp(row["last_authenticated_at"], "authentication")
        last_seen_at = _optional_timestamp(row["last_seen_at"], "activity")
        methods = tuple(str(value) for value in row["authentication_methods"])
        if not methods:
            raise RuntimeError("native session authentication methods are empty")
        return NativeSessionSnapshot(
            session_id=UUID(str(row["session_id"])),
            native_identity_id=UUID(str(row["native_identity_id"])),
            identity_authority_id=UUID(str(row["identity_authority_id"])),
            password_credential_id=_uuid_or_none(row["password_credential_id"]),
            password_credential_status=_credential_status(row["password_credential_status"]),
            webauthn_credential_id=_uuid_or_none(row["webauthn_credential_id"]),
            webauthn_credential_status=_credential_status(row["webauthn_credential_status"]),
            token_digest=bytes(row["token_digest"]),  # type: ignore[arg-type]
            session_epoch=int(row["session_epoch"]),  # type: ignore[arg-type]
            current_session_epoch=int(row["current_session_epoch"]),  # type: ignore[arg-type]
            session_status=NativeSessionStatus(str(row["session_status"])),
            identity_status=NativeIdentityStatus(str(row["identity_status"])),
            authority_status=NativeIdentityAuthorityStatus(str(row["authority_status"])),
            authentication_methods=methods,
            authentication_assurance=AuthenticationAssurance(str(row["authentication_assurance"])),
            user_verified=bool(row["user_verified"]),
            recovery_derived=bool(row["recovery_derived"]),
            expires_at=expires_at,
            created_at=created_at,
            last_seen_at=last_seen_at,
            authenticated_at=authenticated_at,
        )


def _timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, datetime):
        raise RuntimeError(f"native session {label} could not be materialized")
    return value


def _optional_timestamp(value: object, label: str) -> datetime | None:
    if value is None:
        return None
    return _timestamp(value, label)


def _uuid_or_none(value: object) -> UUID | None:
    if value is None:
        return None
    return UUID(str(value))


def _credential_status(value: object) -> NativeCredentialStatus | None:
    if value is None:
        return None
    return NativeCredentialStatus(str(value))
