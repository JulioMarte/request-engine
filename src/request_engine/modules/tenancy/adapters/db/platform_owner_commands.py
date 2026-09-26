import asyncio
import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Never
from uuid import UUID, uuid4, uuid5

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from request_engine.modules.tenancy.application.commands.platform_owner_lifecycle import (
    ActivatePlatformOwnerInvitationCommand,
    CreatePlatformOwnerInvitationCommand,
    EnrollPlatformOwnerInvitationCommand,
    PlatformOwnerConflict,
    PlatformOwnerError,
    PlatformOwnerForbidden,
    PlatformOwnerInvalid,
    PlatformOwnerInvitationEnrollmentResult,
    PlatformOwnerInvitationResult,
    PlatformOwnerLifecycleAction,
    PlatformOwnerLifecycleResult,
    PlatformOwnerProvisioningResult,
    PlatformOwnerRevisionConflict,
    ProvisionPlatformOwnerCommand,
    RevokePlatformOwnerInvitationCommand,
    TransitionPlatformOwnerCommand,
)
from request_engine.platform.db.session import SessionFactory, platform_actor_transaction
from request_engine.platform.security.context import PrincipalKind
from request_engine.platform.security.native_auth import (
    hash_password,
    normalize_login_handle,
)
from request_engine.platform.security.platform_context import PlatformActorContext

_OWNER_NAMESPACE = UUID("9e24e794-70ff-4b88-b6d5-15c5b315db48")
_PROVISION_CAPABILITY = "platform.owner.provision"
_LIFECYCLE_CAPABILITY = "platform.owner.manage_lifecycle"
_DATABASE_ERRORS: dict[str, type[PlatformOwnerError]] = {
    "23505": PlatformOwnerConflict,
    "23514": PlatformOwnerInvalid,
    "22023": PlatformOwnerInvalid,
    "40001": PlatformOwnerRevisionConflict,
    "40P01": PlatformOwnerRevisionConflict,
    "42501": PlatformOwnerForbidden,
    "28000": PlatformOwnerForbidden,
    "55000": PlatformOwnerConflict,
}


class PostgresPlatformOwnerCommands:
    def __init__(self, session_factory: SessionFactory, *, native_authority_id: UUID) -> None:
        self._session_factory = session_factory
        self._native_authority_id = native_authority_id

    async def create_invitation(
        self,
        actor: PlatformActorContext,
        command: CreatePlatformOwnerInvitationCommand,
    ) -> PlatformOwnerInvitationResult:
        if actor.principal_kind is not PrincipalKind.HUMAN or not actor.allows(
            _PROVISION_CAPABILITY
        ):
            raise PlatformOwnerForbidden(_PROVISION_CAPABILITY)
        raw_token = secrets.token_urlsafe(32)
        token_digest = hashlib.sha256(raw_token.encode("utf-8")).digest()
        fingerprint = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()[:16]
        expires_at = datetime.now(UTC) + timedelta(hours=24)
        normalized_provenance = command.provenance_reference.strip()
        intent_digest = _digest_json({"provenance_reference": normalized_provenance})
        key_digest = hashlib.sha256(command.idempotency_key.strip().encode("utf-8")).hexdigest()
        invitation_id = uuid5(
            _OWNER_NAMESPACE,
            f"invitation:{actor.principal_id}:{key_digest}",
        )
        try:
            async with platform_actor_transaction(self._session_factory, actor) as session:
                row = (
                    await session.execute(
                        text(
                            """
                            SELECT * FROM request_platform.create_platform_owner_invitation(
                                CAST(:invitation_id AS uuid),
                                CAST(:token_digest AS bytea),
                                CAST(:fingerprint AS text),
                                CAST(:expires_at AS timestamptz),
                                CAST(:provenance AS text),
                                CAST(:key_digest AS text),
                                CAST(:intent_digest AS text)
                            )
                            """
                        ),
                        {
                            "invitation_id": invitation_id,
                            "token_digest": token_digest,
                            "fingerprint": fingerprint,
                            "expires_at": expires_at,
                            "provenance": normalized_provenance,
                            "key_digest": key_digest,
                            "intent_digest": intent_digest,
                        },
                    )
                ).one()
        except DBAPIError as exc:
            _raise_mapped(exc)
        return PlatformOwnerInvitationResult(
            invitation_id=UUID(str(row[0])),
            raw_token=raw_token if bool(row[1]) else None,
            expires_at=row[3],
            created=bool(row[1]),
        )

    async def enroll_invitation(
        self,
        command: EnrollPlatformOwnerInvitationCommand,
    ) -> PlatformOwnerInvitationEnrollmentResult:
        normalized_login = normalize_login_handle(command.login_handle)
        verifier = await asyncio.to_thread(hash_password, command.password)
        token_digest = hashlib.sha256(command.raw_token.encode("utf-8")).digest()
        native_identity_id = uuid4()
        credential_id = uuid4()
        try:
            async with self._session_factory() as session, session.begin():
                row = (
                    await session.execute(
                        text(
                            """
                            SELECT * FROM request_platform.enroll_platform_owner_invitation(
                                CAST(:token_digest AS bytea),
                                CAST(:identity_id AS uuid),
                                CAST(:credential_id AS uuid),
                                CAST(:login_handle AS text),
                                CAST(:verifier AS text)
                            )
                            """
                        ),
                        {
                            "token_digest": token_digest,
                            "identity_id": native_identity_id,
                            "credential_id": credential_id,
                            "login_handle": normalized_login,
                            "verifier": verifier,
                        },
                    )
                ).one_or_none()
        except DBAPIError as exc:
            _raise_mapped(exc)
        if row is None:
            raise PlatformOwnerInvalid("invitation is invalid, expired, or no longer usable")
        return PlatformOwnerInvitationEnrollmentResult(
            invitation_id=UUID(str(row[0])),
            native_identity_id=UUID(str(row[1])),
        )

    async def revoke_invitation(
        self,
        actor: PlatformActorContext,
        command: RevokePlatformOwnerInvitationCommand,
    ) -> int:
        if actor.principal_kind is not PrincipalKind.HUMAN or not actor.allows(
            _PROVISION_CAPABILITY
        ):
            raise PlatformOwnerForbidden(_PROVISION_CAPABILITY)
        key_digest = hashlib.sha256(command.idempotency_key.strip().encode("utf-8")).hexdigest()
        intent_digest = _digest_json(
            {
                "invitation_id": str(command.invitation_id),
                "reason_code": command.reason_code.strip(),
            }
        )
        try:
            async with platform_actor_transaction(self._session_factory, actor) as session:
                revision = (
                    await session.execute(
                        text(
                            """
                            SELECT request_platform.revoke_platform_owner_invitation(
                                CAST(:invitation_id AS uuid),
                                CAST(:reason_code AS text),
                                CAST(:key_digest AS text),
                                CAST(:intent_digest AS text)
                            )
                            """
                        ),
                        {
                            "invitation_id": command.invitation_id,
                            "reason_code": command.reason_code.strip(),
                            "key_digest": key_digest,
                            "intent_digest": intent_digest,
                        },
                    )
                ).scalar_one()
        except DBAPIError as exc:
            _raise_mapped(exc)
        return int(revision)

    async def activate_invitation(
        self,
        actor: PlatformActorContext,
        command: ActivatePlatformOwnerInvitationCommand,
    ) -> PlatformOwnerProvisioningResult:
        if actor.principal_kind is not PrincipalKind.HUMAN or not actor.allows(
            _PROVISION_CAPABILITY
        ):
            raise PlatformOwnerForbidden(_PROVISION_CAPABILITY)
        key_digest = hashlib.sha256(command.idempotency_key.strip().encode("utf-8")).hexdigest()
        intent_digest = _digest_json({"invitation_id": str(command.invitation_id)})
        operation_id = uuid5(_OWNER_NAMESPACE, f"activate:{command.invitation_id}")
        principal_id = uuid5(operation_id, "principal")
        binding_id = uuid5(operation_id, "binding")
        try:
            async with platform_actor_transaction(self._session_factory, actor) as session:
                row = (
                    await session.execute(
                        text(
                            """
                            SELECT * FROM request_platform.activate_platform_owner_invitation(
                                CAST(:invitation_id AS uuid),
                                CAST(:principal_id AS uuid),
                                CAST(:binding_id AS uuid),
                                CAST(:key_digest AS text),
                                CAST(:intent_digest AS text)
                            )
                            """
                        ),
                        {
                            "invitation_id": command.invitation_id,
                            "principal_id": principal_id,
                            "binding_id": binding_id,
                            "key_digest": key_digest,
                            "intent_digest": intent_digest,
                        },
                    )
                ).one()
        except DBAPIError as exc:
            _raise_mapped(exc)
        return PlatformOwnerProvisioningResult(
            principal_id=UUID(str(row[0])),
            binding_id=UUID(str(row[1])),
        )

    async def provision_owner(
        self,
        actor: PlatformActorContext,
        command: ProvisionPlatformOwnerCommand,
    ) -> PlatformOwnerProvisioningResult:
        if actor.principal_kind is not PrincipalKind.HUMAN or not actor.allows(
            _PROVISION_CAPABILITY
        ):
            raise PlatformOwnerForbidden(_PROVISION_CAPABILITY)
        normalized_provenance = command.provenance_reference.strip()
        intent = {
            "native_identity_id": str(command.native_identity_id),
            "provenance_reference": normalized_provenance,
        }
        intent_digest = _digest_json(intent)
        key_digest = hashlib.sha256(command.idempotency_key.strip().encode("utf-8")).hexdigest()
        operation_id = uuid5(
            _OWNER_NAMESPACE,
            f"{actor.principal_id}:{key_digest}",
        )
        principal_id = uuid5(operation_id, "principal")
        binding_id = uuid5(operation_id, "binding")
        try:
            async with platform_actor_transaction(self._session_factory, actor) as session:
                created = (
                    await session.execute(
                        text(
                            """
                            SELECT request_platform.provision_native_platform_owner(
                                CAST(:principal_id AS uuid),
                                CAST(:binding_id AS uuid),
                                CAST(:authority_id AS uuid),
                                CAST(:identity_id AS uuid),
                                CAST(:provenance AS text),
                                CAST(:key_digest AS text),
                                CAST(:intent_digest AS text)
                            )
                            """
                        ),
                        {
                            "principal_id": principal_id,
                            "binding_id": binding_id,
                            "authority_id": self._native_authority_id,
                            "identity_id": command.native_identity_id,
                            "provenance": normalized_provenance,
                            "key_digest": key_digest,
                            "intent_digest": intent_digest,
                        },
                    )
                ).scalar_one()
        except DBAPIError as exc:
            _raise_mapped(exc)
        return PlatformOwnerProvisioningResult(
            principal_id=UUID(str(created)),
            binding_id=binding_id,
        )

    async def transition_owner(
        self,
        actor: PlatformActorContext,
        command: TransitionPlatformOwnerCommand,
    ) -> PlatformOwnerLifecycleResult:
        if actor.principal_kind is not PrincipalKind.HUMAN or not actor.allows(
            _LIFECYCLE_CAPABILITY
        ):
            raise PlatformOwnerForbidden(_LIFECYCLE_CAPABILITY)
        intent = {
            "principal_id": str(command.principal_id),
            "action": command.action.value,
            "reason_code": command.normalized_reason_code,
            "external_case_reference": command.normalized_case_reference,
        }
        intent_digest = _digest_json(intent)
        key_digest = hashlib.sha256(command.idempotency_key.strip().encode("utf-8")).hexdigest()
        try:
            async with platform_actor_transaction(self._session_factory, actor) as session:
                row = (
                    await session.execute(
                        text(
                            """
                            SELECT * FROM request_platform.transition_native_platform_owner(
                                CAST(:principal_id AS uuid),
                                CAST(:action AS text),
                                CAST(:expected_revision AS bigint),
                                CAST(:reason_code AS text),
                                CAST(:case_reference AS text),
                                CAST(:key_digest AS text),
                                CAST(:intent_digest AS text)
                            )
                            """
                        ),
                        {
                            "principal_id": command.principal_id,
                            "action": command.action.value,
                            "expected_revision": command.expected_revision,
                            "reason_code": command.normalized_reason_code,
                            "case_reference": command.normalized_case_reference,
                            "key_digest": key_digest,
                            "intent_digest": intent_digest,
                        },
                    )
                ).one()
        except DBAPIError as exc:
            _raise_mapped(exc)
        return PlatformOwnerLifecycleResult(
            fact_id=UUID(str(row[0])),
            principal_id=UUID(str(row[1])),
            action=PlatformOwnerLifecycleAction(str(row[2])),
            authority_revision=int(row[3]),
            binding_id=None if row[4] is None else UUID(str(row[4])),
            binding_status=None if row[5] is None else str(row[5]),
        )


def _digest_json(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _raise_mapped(exc: DBAPIError) -> Never:
    error_type = _DATABASE_ERRORS.get(str(getattr(exc.orig, "sqlstate", "")))
    if error_type is None:
        raise exc
    raise error_type() from None
