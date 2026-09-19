"""Least-privilege Instance setup/claim persistence (ADR 0014 §5-§9).

The control-plane login reaches installation state only through the narrow
``request_platform`` setup functions; it never touches tables directly. Each
operation is one explicit transaction and the atomic claim is delegated to the
single ``finalize_instance_claim`` command, which owns the serialization root.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.instance_setup import (
    ClaimReadiness,
    InstanceClaimResult,
    InstanceSnapshot,
    SetupSessionSnapshot,
)

# PostgreSQL SQLSTATEs the setup functions use for expected, closed outcomes.
_CLOSED_OUTCOMES = frozenset({"55000", "54000", "22023"})


class PostgresInstanceSetupStore:
    """Instance setup/claim store backed by the control-plane function surface."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def read_instance(self) -> InstanceSnapshot | None:
        async with self._session_factory() as session, session.begin():
            row = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT id, state, claimed_at, initial_owner_principal_id,
                                   built_in_native_authority_id,
                                   built_in_workload_authority_id
                              FROM request_platform.read_platform_instance()
                            """
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        return InstanceSnapshot(
            instance_id=UUID(str(row["id"])),
            state=str(row["state"]),
            claimed_at=_timestamp_or_none(row["claimed_at"]),
            initial_owner_principal_id=_uuid_or_none(row["initial_owner_principal_id"]),
            built_in_native_authority_id=UUID(str(row["built_in_native_authority_id"])),
            built_in_workload_authority_id=UUID(str(row["built_in_workload_authority_id"])),
        )

    async def create_setup_session(
        self,
        *,
        setup_session_id: UUID,
        token_digest: bytes,
        token_fingerprint: str,
        mode: str,
        ttl_seconds: int,
    ) -> UUID | None:
        try:
            async with self._session_factory() as session, session.begin():
                created = await session.scalar(
                    text(
                        """
                        SELECT request_platform.create_setup_session(
                            :setup_session_id, :token_digest, :token_fingerprint,
                            :mode, :ttl_seconds
                        )
                        """
                    ),
                    {
                        "setup_session_id": setup_session_id,
                        "token_digest": token_digest,
                        "token_fingerprint": token_fingerprint,
                        "mode": mode,
                        "ttl_seconds": ttl_seconds,
                    },
                )
        except DBAPIError as error:
            if _sqlstate(error) in _CLOSED_OUTCOMES:
                return None
            raise
        return None if created is None else UUID(str(created))

    async def read_setup_session(self, *, token_digest: bytes) -> SetupSessionSnapshot | None:
        async with self._session_factory() as session, session.begin():
            row = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT id, status, expires_at, instance_state, is_usable
                              FROM request_platform.read_setup_session(:token_digest)
                            """
                        ),
                        {"token_digest": token_digest},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        return SetupSessionSnapshot(
            setup_session_id=UUID(str(row["id"])),
            status=str(row["status"]),
            is_usable=bool(row["is_usable"]),
            expires_at=_timestamp(row["expires_at"], "setup session expiry"),
            instance_state=str(row["instance_state"]),
        )

    async def set_pending_identity(
        self,
        *,
        native_identity_id: UUID,
        setup_session_id: UUID,
        login_handle: str,
        verifier: str,
    ) -> bool:
        async with self._session_factory() as session, session.begin():
            created = await session.scalar(
                text(
                    """
                    SELECT request_platform.set_setup_pending_identity(
                        :native_identity_id, :setup_session_id, :login_handle, :verifier
                    )
                    """
                ),
                {
                    "native_identity_id": native_identity_id,
                    "setup_session_id": setup_session_id,
                    "login_handle": login_handle,
                    "verifier": verifier,
                },
            )
        return created is True

    async def read_claim_readiness(self, *, setup_session_id: UUID) -> ClaimReadiness | None:
        async with self._session_factory() as session, session.begin():
            row = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT setup_status, setup_usable, instance_state,
                                   has_identity, verified_webauthn_count,
                                   has_recovery_codes, policy_key
                              FROM request_platform.read_claim_readiness(
                                  :setup_session_id
                              )
                            """
                        ),
                        {"setup_session_id": setup_session_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        return ClaimReadiness(
            setup_status=str(row["setup_status"]),
            setup_usable=bool(row["setup_usable"]),
            instance_state=str(row["instance_state"]),
            has_identity=bool(row["has_identity"]),
            verified_webauthn_count=int(row["verified_webauthn_count"]),
            has_recovery_codes=bool(row["has_recovery_codes"]),
            policy_key=str(row["policy_key"]),
        )

    async def finalize_claim(
        self,
        *,
        setup_session_id: UUID,
        idempotency_key_digest: str,
        intent_digest: str,
        claim_provenance: str,
        actor_authentication_method: str,
        correlation_id: UUID | None,
    ) -> InstanceClaimResult | None:
        try:
            async with self._session_factory() as session, session.begin():
                row = (
                    (
                        await session.execute(
                            text(
                                """
                                SELECT instance_id, owner_principal_id,
                                       native_identity_id, setup_session_id,
                                       policy_key
                                  FROM request_platform.finalize_instance_claim(
                                      :setup_session_id, :idempotency_key_digest,
                                      :intent_digest, :claim_provenance,
                                      :actor_authentication_method, :correlation_id
                                  )
                                """
                            ),
                            {
                                "setup_session_id": setup_session_id,
                                "idempotency_key_digest": idempotency_key_digest,
                                "intent_digest": intent_digest,
                                "claim_provenance": claim_provenance,
                                "actor_authentication_method": actor_authentication_method,
                                "correlation_id": correlation_id,
                            },
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
        except DBAPIError as error:
            if _sqlstate(error) in _CLOSED_OUTCOMES:
                return None
            raise
        return None if row is None else _claim_result(dict(row))

    async def read_installation_claim(
        self, *, idempotency_key_digest: str
    ) -> InstanceClaimResult | None:
        async with self._session_factory() as session, session.begin():
            row = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT instance_id, owner_principal_id, native_identity_id,
                                   setup_session_id, policy_key
                              FROM request_platform.read_installation_claim(
                                  :idempotency_key_digest
                              )
                            """
                        ),
                        {"idempotency_key_digest": idempotency_key_digest},
                    )
                )
                .mappings()
                .one_or_none()
            )
        return None if row is None else _claim_result(dict(row))


def _claim_result(row: Mapping[str, Any]) -> InstanceClaimResult:
    return InstanceClaimResult(
        instance_id=UUID(str(row["instance_id"])),
        owner_principal_id=UUID(str(row["owner_principal_id"])),
        native_identity_id=UUID(str(row["native_identity_id"])),
        setup_session_id=UUID(str(row["setup_session_id"])),
        policy_key=str(row["policy_key"]),
    )


def _sqlstate(error: DBAPIError) -> str | None:
    state = getattr(error.orig, "sqlstate", None)
    return None if state is None else str(state)


def _timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, datetime):
        raise RuntimeError(f"{label} could not be materialized")
    return value


def _timestamp_or_none(value: object) -> datetime | None:
    return None if value is None else _timestamp(value, "timestamp")


def _uuid_or_none(value: object) -> UUID | None:
    return None if value is None else UUID(str(value))


__all__ = ["PostgresInstanceSetupStore"]
