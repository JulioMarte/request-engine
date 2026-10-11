"""Committed lease -> metadata-only provider reconciliation -> fenced result."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

import httpx
from sqlalchemy import text

from request_engine.platform.db.session import SessionFactory
from request_engine.platform.secrets.temporary_proof_cleanup_acceptance import (
    TemporaryProofExpiryReceipt,
    inspect_expired_temporary_version,
    submit_temporary_version_destruction,
)
from request_engine.platform.secrets.temporary_proof_cleanup_admission import (
    TemporaryCleanupAdmission,
)


@dataclass(frozen=True, slots=True)
class TemporaryCleanupLease:
    work_id: UUID
    lease_token: UUID
    lease_until: datetime
    admitted_at: datetime
    attempt: int
    receipt: TemporaryProofExpiryReceipt


class TemporaryProofCleanupWorker:
    """No provider transport until operator admission and committed technical claim.

    Runtime LOGIN must belong exclusively to request_proof_cleanup_worker; primitives
    enforce its real session identity. It cannot stage/read plaintext, record a
    business fact, enumerate a namespace, or delete metadata. Late lease holders
    cannot finalize; destroy is safe to reconcile only while version identities
    cannot be recreated under the externally certified provider policy.
    """

    def __init__(
        self,
        sessions: SessionFactory,
        client: httpx.AsyncClient,
        *,
        admission: TemporaryCleanupAdmission,
        token: str,
        outbound_fenced: bool = True,
        lease_seconds: int = 60,
        retry_seconds: int = 60,
    ) -> None:
        if not token or not 10 <= lease_seconds <= 3600 or not 1 <= retry_seconds <= 86400:
            raise ValueError("invalid cleanup worker configuration")
        if client.follow_redirects:
            raise ValueError("cleanup worker redirects are forbidden")
        if any(
            value is None or not 0 < value <= 5
            for value in (
                client.timeout.connect,
                client.timeout.read,
                client.timeout.write,
                client.timeout.pool,
            )
        ):
            raise ValueError("cleanup worker requires bounded provider timeouts")
        self._sessions, self._client = sessions, client
        self._admission, self._headers = admission, {"X-Vault-Token": token}
        self._fenced, self._lease_seconds, self._retry_seconds = (
            outbound_fenced,
            lease_seconds,
            retry_seconds,
        )

    def _admit(self) -> None:
        self._admission.assert_current(
            now=datetime.now(UTC),
            provider_origin=str(self._client.base_url),
            outbound_fenced=self._fenced,
        )

    async def claim(self) -> TemporaryCleanupLease | None:
        self._admit()
        async with self._sessions() as session, session.begin():
            row = (
                (
                    await session.execute(
                        text(
                            "SELECT * FROM request_cmd.claim_temporary_proof_cleanup(:b,:m,:g,:l)"
                        ),
                        {
                            "b": self._admission.backend_id,
                            "m": self._admission.mount,
                            "g": self._admission.grace_seconds,
                            "l": self._lease_seconds,
                        },
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                return None
            claim = TemporaryCleanupLease(
                cast(UUID, row["work_id"]),
                cast(UUID, row["lease_token"]),
                cast(datetime, row["lease_until"]),
                cast(datetime, row["admitted_at"]),
                cast(int, row["attempt"]),
                TemporaryProofExpiryReceipt(
                    cast(str, row["reference"]),
                    cast(int, row["version"]),
                    cast(datetime, row["expires_at"]),
                    cast(datetime, row["created_at"]),
                    cast(datetime, row["deletion_at"]),
                ),
            )
        return claim  # Transaction/locks are closed before the caller can do I/O.

    async def reconcile(self, claim: TemporaryCleanupLease) -> str:
        self._admit()
        if datetime.now(UTC) >= claim.lease_until:
            return "unresolved"
        grace = timedelta(seconds=self._admission.grace_seconds)
        if claim.admitted_at < claim.receipt.expires_at + grace:
            return "retained"

        async def inspect() -> str:
            self._admit()
            return await inspect_expired_temporary_version(
                self._client,
                headers=self._headers,
                receipt=claim.receipt,
                now=claim.admitted_at,
                grace=grace,
                mount=self._admission.mount,
            )

        initial = await inspect()
        if initial != "eligible":
            return initial
        self._admit()
        if datetime.now(UTC) >= claim.lease_until:
            return "unresolved"
        submitted = await submit_temporary_version_destruction(
            self._client,
            headers=self._headers,
            receipt=claim.receipt,
            mount=self._admission.mount,
        )
        if submitted == "denied":
            return "denied"
        final = await inspect()
        return "unresolved" if final == "eligible" else final

    async def finish(self, claim: TemporaryCleanupLease, outcome: str) -> bool:
        self._admit()
        async with self._sessions() as session, session.begin():
            result = await session.execute(
                text("SELECT request_cmd.finish_temporary_proof_cleanup(:w,:l,:o,:a,:d,:r)"),
                {
                    "w": claim.work_id,
                    "l": claim.lease_token,
                    "o": outcome,
                    "a": self._admission.admission_id,
                    "d": self._admission.artifact_digest,
                    "r": self._retry_seconds,
                },
            )
            return result.scalar_one() is True

    async def run_once(self) -> str:
        claim = await self.claim()
        if claim is None:
            return "idle"
        outcome = await self.reconcile(claim)
        return outcome if await self.finish(claim, outcome) else "fenced"
