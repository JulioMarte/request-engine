"""Least-privilege recovery-code persistence through ``request_auth``."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text

from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.recovery_codes import (
    NativeRecoveryReadiness,
    RecoveryCodeConsumed,
    RecoveryCodeSetSummary,
)


class PostgresRecoveryCodeStore:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def create_set(
        self,
        *,
        set_id: UUID,
        code_digests: Sequence[bytes],
        native_identity_id: UUID | None = None,
        setup_session_id: UUID | None = None,
    ) -> bool:
        async with self._session_factory() as session, session.begin():
            created = await session.scalar(
                text(
                    """
                    SELECT request_auth.create_recovery_code_set(
                        :set_id, :native_identity_id, :setup_session_id, :code_digests
                    )
                    """
                ),
                {
                    "set_id": set_id,
                    "native_identity_id": native_identity_id,
                    "setup_session_id": setup_session_id,
                    "code_digests": list(code_digests),
                },
            )
        return created is True

    async def consume(self, *, code_digest: bytes) -> RecoveryCodeConsumed | None:
        async with self._session_factory() as session, session.begin():
            row = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT native_identity_id, set_id, code_id
                              FROM request_auth.consume_recovery_code(:code_digest)
                            """
                        ),
                        {"code_digest": code_digest},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        return RecoveryCodeConsumed(
            native_identity_id=UUID(str(row["native_identity_id"])),
            set_id=UUID(str(row["set_id"])),
            code_id=UUID(str(row["code_id"])),
        )

    async def consume_and_rotate_password(
        self,
        *,
        code_digest: bytes,
        new_credential_id: UUID,
        new_verifier: str,
    ) -> UUID | None:
        async with self._session_factory() as session, session.begin():
            value = await session.scalar(
                text(
                    """
                    SELECT request_auth.consume_recovery_code_and_rotate_password(
                        :code_digest, :new_credential_id, :new_verifier
                    )
                    """
                ),
                {
                    "code_digest": code_digest,
                    "new_credential_id": new_credential_id,
                    "new_verifier": new_verifier,
                },
            )
        if value is None:
            return None
        return UUID(str(value))

    async def readiness(self, *, native_identity_id: UUID) -> NativeRecoveryReadiness | None:
        async with self._session_factory() as session, session.begin():
            row = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT recovery_state, recovery_epoch, last_recovered_at,
                                   last_recovery_method, completed_at, active_code_set,
                                   remaining_codes, active_webauthn_credentials
                              FROM request_auth.read_native_recovery_readiness(
                                  :native_identity_id
                              )
                            """
                        ),
                        {"native_identity_id": native_identity_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        return NativeRecoveryReadiness(
            recovery_state=str(row["recovery_state"]),
            recovery_epoch=int(row["recovery_epoch"]),
            last_recovered_at=_datetime_or_none(row["last_recovered_at"]),
            last_recovery_method=(
                None if row["last_recovery_method"] is None else str(row["last_recovery_method"])
            ),
            completed_at=_datetime_or_none(row["completed_at"]),
            active_code_set=bool(row["active_code_set"]),
            remaining_codes=int(row["remaining_codes"]),
            active_webauthn_credentials=int(row["active_webauthn_credentials"]),
        )

    async def complete_recovery(self, *, native_identity_id: UUID) -> bool:
        return await self._call_boolean(
            "SELECT request_auth.complete_native_recovery(:native_identity_id)",
            {"native_identity_id": native_identity_id},
        )

    async def promote(self, *, set_id: UUID, native_identity_id: UUID) -> bool:
        return await self._call_boolean(
            "SELECT request_auth.promote_recovery_code_set(:set_id, :native_identity_id)",
            {"set_id": set_id, "native_identity_id": native_identity_id},
        )

    async def revoke(self, *, set_id: UUID, reason: str) -> bool:
        return await self._call_boolean(
            "SELECT request_auth.revoke_recovery_code_set(:set_id, :reason)",
            {"set_id": set_id, "reason": reason},
        )

    async def summary(self, *, native_identity_id: UUID) -> tuple[RecoveryCodeSetSummary, ...]:
        async with self._session_factory() as session, session.begin():
            rows = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT set_id, version, status, created_at,
                                   total_codes, remaining_codes
                              FROM request_auth.read_recovery_code_set_summary(
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
        return tuple(_summary(dict(row)) for row in rows)

    async def _call_boolean(self, statement: str, parameters: dict[str, object]) -> bool:
        async with self._session_factory() as session, session.begin():
            value = (await session.execute(text(statement), parameters)).scalar_one()
        return bool(value)


def _summary(row: Mapping[str, Any]) -> RecoveryCodeSetSummary:
    created_at = row["created_at"]
    if not isinstance(created_at, datetime):
        raise RuntimeError("recovery code set creation could not be materialized")
    return RecoveryCodeSetSummary(
        set_id=UUID(str(row["set_id"])),
        version=int(row["version"]),
        status=str(row["status"]),
        created_at=created_at,
        total_codes=int(row["total_codes"]),
        remaining_codes=int(row["remaining_codes"]),
    )


def _datetime_or_none(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, datetime):
        raise RuntimeError("native recovery timestamp could not be materialized")
    return value
