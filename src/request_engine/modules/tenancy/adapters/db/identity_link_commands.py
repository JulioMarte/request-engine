import re
from datetime import datetime
from typing import NoReturn, Protocol, runtime_checkable
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from request_engine.modules.tenancy.application.commands.identity_link import (
    IDENTITY_LINK_CAPABILITY,
    ConfirmIdentityLinkIntentCommand,
    CreateIdentityLinkIntentCommand,
    IdentityLinkBindingReceipt,
    IdentityLinkIntentReceipt,
)
from request_engine.modules.tenancy.application.errors import (
    IdentityLinkConflict,
    IdentityLinkForbidden,
    IdentityLinkInputInvalid,
    IdentityLinkNotFound,
    IdentityLinkRevisionConflict,
)
from request_engine.platform.db.session import SessionFactory, actor_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)
from request_engine.platform.security.context import ActorContext, PrincipalKind

_NONCE_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_MIN_TTL_SECONDS = 60
_MAX_TTL_SECONDS = 900


@runtime_checkable
class _HasSqlState(Protocol):
    sqlstate: str | None


def _validate_provenance_reference(value: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 400:
        raise ValueError("provenance_reference must contain between 1 and 400 characters")
    return normalized


def _validate_idempotency_key(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("idempotency_key is required")
    return normalized


def _validate_nonce_digest(value: str) -> str:
    normalized = value.strip()
    if _NONCE_DIGEST_RE.fullmatch(normalized) is None:
        raise ValueError("nonce_digest must be a 64-character lowercase hexadecimal digest")
    return normalized


def _validate_ttl_seconds(value: int) -> int:
    if value < _MIN_TTL_SECONDS or value > _MAX_TTL_SECONDS:
        raise ValueError("ttl_seconds must be between 60 and 900")
    return value


def _require_human_actor(actor: ActorContext) -> None:
    if actor.principal_kind is not PrincipalKind.HUMAN:
        raise IdentityLinkForbidden("self-service identity linking requires a HUMAN actor")


def _raise_identity_link_db_error(exc: DBAPIError) -> NoReturn:
    sqlstate = exc.orig.sqlstate if isinstance(exc.orig, _HasSqlState) else None
    if sqlstate in {"28000", "42501"}:
        raise IdentityLinkForbidden("identity link authority was denied") from exc
    if sqlstate == "P0002":
        raise IdentityLinkNotFound("identity link intent is not visible in this tenant") from exc
    if sqlstate in {"40001", "40P01"}:
        raise IdentityLinkRevisionConflict("identity link actor binding revision is stale") from exc
    if sqlstate in {"23505", "23514", "55000"}:
        raise IdentityLinkConflict("identity link state conflicts with this request") from exc
    if sqlstate == "22023":
        raise IdentityLinkInputInvalid("identity link input was rejected") from exc
    raise exc


def _replay_positive_int(replay: dict[str, object], key: str) -> int:
    value = replay.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise RuntimeError(f"completed identity link idempotency replay has invalid {key}")
    return value


def _replay_uuid(replay: dict[str, object], key: str) -> UUID:
    value = replay.get(key)
    if not isinstance(value, str):
        raise RuntimeError(f"completed identity link idempotency replay has invalid {key}")
    return UUID(value)


def _replay_datetime(replay: dict[str, object], key: str) -> datetime:
    value = replay.get(key)
    if not isinstance(value, str):
        raise RuntimeError(f"completed identity link idempotency replay has invalid {key}")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise RuntimeError(f"completed identity link idempotency replay has naive {key}")
    return parsed


class PostgresIdentityLinkCommands:
    """Typed, idempotent application boundary over self-service identity linking."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def create_identity_link_intent(
        self,
        actor: ActorContext,
        command: CreateIdentityLinkIntentCommand,
    ) -> IdentityLinkIntentReceipt:
        _require_human_actor(actor)
        provenance = _validate_provenance_reference(command.provenance_reference)
        idempotency_key = _validate_idempotency_key(command.idempotency_key)
        nonce_digest = _validate_nonce_digest(command.nonce_digest)
        ttl_seconds = _validate_ttl_seconds(command.ttl_seconds)
        fingerprint = command_fingerprint(
            IDENTITY_LINK_CAPABILITY,
            {
                "target_authority_id": command.target_authority_id,
                "ttl_seconds": ttl_seconds,
                "provenance_reference": provenance,
            },
        )
        async with actor_transaction(self._session_factory, actor) as session:
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=actor.organization_id,
                principal_id=actor.principal_id,
                capability=IDENTITY_LINK_CAPABILITY,
                idempotency_key=idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return IdentityLinkIntentReceipt(
                    intent_id=_replay_uuid(replay, "intent_id"),
                    expires_at=_replay_datetime(replay, "expires_at"),
                    target_authority_id=_replay_uuid(replay, "target_authority_id"),
                )
            try:
                result = (
                    (
                        await session.execute(
                            text(
                                """
                                SELECT intent_id, expires_at, target_authority_id
                                  FROM request_engine.create_identity_link_intent(
                                      :intent_id,
                                      :actor_binding_id,
                                      :target_authority_id,
                                      :nonce_digest,
                                      :ttl_seconds,
                                      :provenance_reference
                                  )
                                """
                            ),
                            {
                                "intent_id": command.intent_id,
                                "actor_binding_id": command.actor_binding_id,
                                "target_authority_id": command.target_authority_id,
                                "nonce_digest": nonce_digest,
                                "ttl_seconds": ttl_seconds,
                                "provenance_reference": provenance,
                            },
                        )
                    )
                    .mappings()
                    .one()
                )
            except DBAPIError as exc:
                _raise_identity_link_db_error(exc)
            receipt = IdentityLinkIntentReceipt(
                intent_id=UUID(str(result["intent_id"])),
                expires_at=result["expires_at"],
                target_authority_id=UUID(str(result["target_authority_id"])),
            )
            await complete_idempotency(
                session,
                idempotency_id,
                {
                    "intent_id": str(receipt.intent_id),
                    "expires_at": receipt.expires_at.isoformat(),
                    "target_authority_id": str(receipt.target_authority_id),
                },
            )
            return receipt

    async def confirm_identity_link_intent(
        self,
        actor: ActorContext,
        command: ConfirmIdentityLinkIntentCommand,
    ) -> IdentityLinkBindingReceipt:
        _require_human_actor(actor)
        if command.expected_actor_binding_revision <= 0:
            raise ValueError("expected_actor_binding_revision must be positive")
        provenance = _validate_provenance_reference(command.provenance_reference)
        idempotency_key = _validate_idempotency_key(command.idempotency_key)
        fingerprint = command_fingerprint(
            IDENTITY_LINK_CAPABILITY,
            {
                "intent_id": command.intent_id,
                "expected_actor_binding_revision": command.expected_actor_binding_revision,
                "native_identity_id": command.native_identity_id,
                "provenance_reference": provenance,
            },
        )
        async with actor_transaction(self._session_factory, actor) as session:
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=actor.organization_id,
                principal_id=actor.principal_id,
                capability=IDENTITY_LINK_CAPABILITY,
                idempotency_key=idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return IdentityLinkBindingReceipt(
                    binding_id=_replay_uuid(replay, "binding_id"),
                    principal_id=_replay_uuid(replay, "principal_id"),
                    binding_revision=_replay_positive_int(replay, "binding_revision"),
                )
            try:
                result = (
                    (
                        await session.execute(
                            text(
                                """
                                SELECT binding_id, principal_id, binding_revision
                                  FROM request_engine.confirm_identity_link_intent(
                                      :intent_id,
                                      :expected_actor_binding_revision,
                                      :native_identity_id,
                                      :binding_id,
                                      :provenance_reference
                                  )
                                """
                            ),
                            {
                                "intent_id": command.intent_id,
                                "expected_actor_binding_revision": (
                                    command.expected_actor_binding_revision
                                ),
                                "native_identity_id": command.native_identity_id,
                                "binding_id": command.binding_id,
                                "provenance_reference": provenance,
                            },
                        )
                    )
                    .mappings()
                    .one()
                )
            except DBAPIError as exc:
                _raise_identity_link_db_error(exc)
            receipt = IdentityLinkBindingReceipt(
                binding_id=UUID(str(result["binding_id"])),
                principal_id=UUID(str(result["principal_id"])),
                binding_revision=int(result["binding_revision"]),
            )
            await complete_idempotency(
                session,
                idempotency_id,
                {
                    "binding_id": str(receipt.binding_id),
                    "principal_id": str(receipt.principal_id),
                    "binding_revision": receipt.binding_revision,
                },
            )
            return receipt
