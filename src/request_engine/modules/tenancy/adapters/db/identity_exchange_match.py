"""PostgreSQL exact-match adapter returning only an opaque S0d candidate reference."""

from uuid import UUID

from request_engine.modules.tenancy.adapters.db.identity_exchange_sql import CREATE_CANDIDATE
from request_engine.modules.tenancy.application.identity_exchange import MatchPortableIdentityCommand
from request_engine.modules.tenancy.application.identity_exchange_errors import IdentityExchangeUnavailable
from request_engine.modules.tenancy.contracts.identity_exchange import IdentityMatchResult
from request_engine.modules.tenancy.domain.identity_exchange import (
    ScopedIdentityDocument,
    identity_document_fingerprint,
)
from request_engine.platform.audit.postgres import append_audit
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)

_CAPABILITY = "identity_exchange.match"


class PostgresPortableIdentityMatcher:
    def __init__(self, session_factory: SessionFactory, fingerprint_key: bytes | None) -> None:
        self._session_factory = session_factory
        self._fingerprint_key = fingerprint_key

    async def match_portable_identity(
        self,
        command: MatchPortableIdentityCommand,
    ) -> IdentityMatchResult:
        authority = command.document_authority
        if authority is None:
            raise IdentityExchangeUnavailable("scoped document authority is required")
        document = ScopedIdentityDocument(
            command.document_kind, authority, command.document_value
        )
        try:
            fingerprint = identity_document_fingerprint(self._fingerprint_key, document)
        except RuntimeError as error:
            raise IdentityExchangeUnavailable(str(error)) from None
        idempotency_fingerprint = command_fingerprint(
            _CAPABILITY,
            {
                "document_kind": document.kind,
                "document_authority": document.authority,
                "fingerprint": fingerprint,
                "proof_kind": command.proof_kind,
            },
        )
        async with tenant_transaction(self._session_factory, command.organization_id) as session:
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability=_CAPABILITY,
                idempotency_key=command.idempotency_key,
                fingerprint=idempotency_fingerprint,
            )
            if replay is not None:
                raw = replay.get("candidate_ref")
                return IdentityMatchResult(
                    matched=bool(replay["matched"]),
                    candidate_ref=UUID(str(raw)) if raw else None,
                )
            candidate = (
                await session.execute(
                    CREATE_CANDIDATE,
                    {
                        "kind": document.kind,
                        "authority": document.authority,
                        "fingerprint": fingerprint,
                        "principal_id": command.principal_id,
                    },
                )
            ).scalar_one_or_none()
            candidate_ref = UUID(str(candidate)) if candidate else None
            result = IdentityMatchResult(matched=candidate_ref is not None, candidate_ref=candidate_ref)
            await append_audit(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                command_name=_CAPABILITY,
                aggregate_kind="IdentityExchangeMatch",
                aggregate_id=candidate_ref or idempotency_id,
                idempotency_id=idempotency_id,
                details={
                    "document_kind": document.kind,
                    "document_authority": document.authority,
                    "matched": result.matched,
                    "proof_kind": command.proof_kind,
                },
            )
            await complete_idempotency(
                session,
                idempotency_id,
                {
                    "matched": result.matched,
                    "candidate_ref": str(candidate_ref) if candidate_ref else None,
                },
            )
            return result
