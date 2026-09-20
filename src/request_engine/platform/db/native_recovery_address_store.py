from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import text

from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.native_recovery_addresses import (
    NativeRecoveryAddress,
    NativeRecoveryAddressPrepared,
    NativeRecoveryDispatch,
)


class PostgresNativeRecoveryAddressStore:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def prepare(
        self,
        *,
        address_id: UUID,
        native_identity_id: UUID,
        kind: str,
        normalized_address: str,
        verification_id: UUID,
        token_digest: bytes,
        token_fingerprint: str,
        expires_at: datetime,
    ) -> NativeRecoveryAddressPrepared | None:
        async with self._session_factory() as session, session.begin():
            row = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT recovery_address_id, address_status, verification_created
                              FROM request_auth.prepare_native_recovery_address(
                                  :address_id,
                                  :native_identity_id,
                                  :kind,
                                  :normalized_address,
                                  :verification_id,
                                  :token_digest,
                                  :token_fingerprint,
                                  :expires_at
                              )
                            """
                        ),
                        {
                            "address_id": address_id,
                            "native_identity_id": native_identity_id,
                            "kind": kind,
                            "normalized_address": normalized_address,
                            "verification_id": verification_id,
                            "token_digest": token_digest,
                            "token_fingerprint": token_fingerprint,
                            "expires_at": expires_at,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        return NativeRecoveryAddressPrepared(
            address_id=UUID(str(row["recovery_address_id"])),
            status=str(row["address_status"]),
            verification_created=bool(row["verification_created"]),
        )

    async def verify(self, *, verification_id: UUID, token_digest: bytes) -> UUID | None:
        async with self._session_factory() as session, session.begin():
            value = (
                await session.execute(
                    text(
                        """
                        SELECT request_auth.verify_native_recovery_address(
                            :verification_id,
                            :token_digest
                        )
                        """
                    ),
                    {
                        "verification_id": verification_id,
                        "token_digest": token_digest,
                    },
                )
            ).scalar_one_or_none()
        return None if value is None else UUID(str(value))

    async def list_for_identity(
        self, *, native_identity_id: UUID
    ) -> tuple[NativeRecoveryAddress, ...]:
        async with self._session_factory() as session, session.begin():
            rows = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT recovery_address_id, kind, normalized_address,
                                   status, revision, verified_at, created_at
                              FROM request_auth.read_native_recovery_addresses(
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
            NativeRecoveryAddress(
                address_id=UUID(str(row["recovery_address_id"])),
                kind=str(row["kind"]),
                normalized_address=str(row["normalized_address"]),
                status=str(row["status"]),
                revision=int(row["revision"]),
                verified_at=_datetime_or_none(row["verified_at"]),
                created_at=_datetime(row["created_at"]),
            )
            for row in rows
        )

    async def revoke(self, *, native_identity_id: UUID, address_id: UUID) -> bool:
        async with self._session_factory() as session, session.begin():
            value = (
                await session.execute(
                    text(
                        """
                        SELECT request_auth.revoke_native_recovery_address(
                            :native_identity_id,
                            :address_id
                        )
                        """
                    ),
                    {
                        "native_identity_id": native_identity_id,
                        "address_id": address_id,
                    },
                )
            ).scalar_one()
        return bool(value)

    async def prepare_recovery(
        self,
        *,
        identity_authority_id: UUID,
        login_handle: str,
        recovery_id: UUID,
        token_digest: bytes,
        token_fingerprint: str,
        expires_at: datetime,
    ) -> NativeRecoveryDispatch | None:
        async with self._session_factory() as session, session.begin():
            row = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT native_identity_id, recovery_address_id, destination_address
                              FROM request_auth.create_native_recovery_intent_for_verified_address(
                                  :identity_authority_id,
                                  :login_handle,
                                  :recovery_id,
                                  :token_digest,
                                  :token_fingerprint,
                                  :expires_at
                              )
                            """
                        ),
                        {
                            "identity_authority_id": identity_authority_id,
                            "login_handle": login_handle,
                            "recovery_id": recovery_id,
                            "token_digest": token_digest,
                            "token_fingerprint": token_fingerprint,
                            "expires_at": expires_at,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        return NativeRecoveryDispatch(
            native_identity_id=UUID(str(row["native_identity_id"])),
            recovery_address_id=UUID(str(row["recovery_address_id"])),
            destination_address=str(row["destination_address"]),
        )


def _datetime(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise RuntimeError("native recovery address timestamp could not be materialized")
    return value


def _datetime_or_none(value: object) -> datetime | None:
    if value is None:
        return None
    return _datetime(value)
