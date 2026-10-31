"""Runtime self-service account surface: enrollment, entitlement read, business creation.

Every operation is one transaction through the runtime application role and narrow
``request_auth`` SECURITY DEFINER functions (migration 0006, ADR 0021).
"""

import hashlib
import json
from typing import Never
from uuid import UUID, uuid4, uuid5

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from request_engine.modules.tenancy.application.commands.account_invitations import (
    AccountEnrollmentUnavailable,
    AccountInvitationEnrollment,
    AccountInvitationInvalid,
    AccountLoginUnavailable,
    AccountPasswordInvalid,
    EnrollAccountInvitationCommand,
)
from request_engine.modules.tenancy.application.commands.self_service_organizations import (
    AccountEntitlementView,
    CreateSelfServiceOrganizationCommand,
    SelfServiceOrganizationCreated,
    SelfServiceOrganizationError,
    SelfServiceOrganizationForbidden,
    SelfServiceOrganizationIdempotencyConflict,
    SelfServiceOrganizationInvalid,
    SelfServiceOrganizationKeyUnavailable,
    SelfServiceOrganizationLimitReached,
)
from request_engine.modules.tenancy.domain.account_entitlement import derive_organization_key
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.authentication import AuthenticatedSubjectClass
from request_engine.platform.security.native_auth import (
    PasswordPolicyViolation,
    hash_password,
    normalize_login_handle,
)
from request_engine.platform.security.password_work import run_password_work
from request_engine.platform.security.subject_http import AuthenticatedHttpSubject

_NAMESPACE = UUID("a4f1f0d2-6c7e-4a51-8f0b-2b1f9d4c3e77")
_CREATE_ERRORS: dict[str, type[SelfServiceOrganizationError]] = {
    "RE409": SelfServiceOrganizationIdempotencyConflict,
    "RE429": SelfServiceOrganizationLimitReached,
    "23505": SelfServiceOrganizationKeyUnavailable,
    "22023": SelfServiceOrganizationInvalid,
    "23514": SelfServiceOrganizationInvalid,
    "42501": SelfServiceOrganizationForbidden,
    "28000": SelfServiceOrganizationForbidden,
}


class PostgresSelfServiceAccountCommands:
    def __init__(self, session_factory: SessionFactory, *, native_authority_id: UUID) -> None:
        self._sessions = session_factory
        self._authority = native_authority_id

    async def enroll(self, command: EnrollAccountInvitationCommand) -> AccountInvitationEnrollment:
        login = normalize_login_handle(command.login_handle)
        try:
            verifier = await run_password_work(hash_password, command.password)
        except PasswordPolicyViolation as exc:
            raise AccountPasswordInvalid("password does not satisfy the native policy") from exc
        identity_id, credential_id, entitlement_id = uuid4(), uuid4(), uuid4()
        try:
            async with self._sessions() as session, session.begin():
                row = (
                    await session.execute(
                        text(
                            "SELECT * FROM request_auth.enroll_account_invitation("
                            "CAST(:authority AS uuid), CAST(:digest AS bytea), "
                            "CAST(:identity AS uuid), CAST(:credential AS uuid), "
                            "CAST(:entitlement AS uuid), CAST(:login AS text), "
                            "CAST(:verifier AS text))"
                        ),
                        {
                            "authority": self._authority,
                            "digest": hashlib.sha256(command.raw_token.encode("utf-8")).digest(),
                            "identity": identity_id,
                            "credential": credential_id,
                            "entitlement": entitlement_id,
                            "login": login,
                            "verifier": verifier,
                        },
                    )
                ).one_or_none()
        except DBAPIError as exc:
            state = str(getattr(exc.orig, "sqlstate", ""))
            if state == "23505":
                raise AccountLoginUnavailable("login handle is unavailable") from None
            if state == "55000":
                raise AccountEnrollmentUnavailable("native authority unavailable") from None
            raise
        if row is None:
            raise AccountInvitationInvalid("invitation is invalid, expired or already used")
        return AccountInvitationEnrollment(
            invitation_id=UUID(str(row[0])),
            native_identity_id=UUID(str(row[1])),
            login_handle=login,
            entitlement_id=UUID(str(row[2])),
            max_organizations=int(row[3]),
        )

    async def read_entitlement(
        self, authenticated: AuthenticatedHttpSubject
    ) -> AccountEntitlementView | None:
        identity, _session = _native_subject(authenticated)
        async with self._sessions() as session, session.begin():
            row = (
                await session.execute(
                    text(
                        "SELECT * FROM request_auth.read_account_entitlement("
                        "CAST(:authority AS uuid), CAST(:identity AS uuid))"
                    ),
                    {"authority": self._authority, "identity": identity},
                )
            ).one_or_none()
        if row is None:
            return None
        return AccountEntitlementView(
            entitlement_id=UUID(str(row[0])),
            status=str(row[1]),
            max_organizations=int(row[2]),
            organizations_created=int(row[3]),
            revision=int(row[4]),
        )

    async def create_organization(
        self,
        authenticated: AuthenticatedHttpSubject,
        command: CreateSelfServiceOrganizationCommand,
        *,
        correlation_id: UUID | None = None,
    ) -> SelfServiceOrganizationCreated:
        identity, session_id = _native_subject(authenticated)
        key_digest = hashlib.sha256(command.idempotency_key.strip().encode("utf-8")).hexdigest()
        operation = uuid5(_NAMESPACE, f"self-service:{identity}:{key_digest}")
        organization_key = command.organization_key or derive_organization_key(
            command.display_name, operation.hex[:6]
        )
        intent = {
            "display_name": command.display_name,
            "organization_key": command.organization_key,
            "timezone": command.timezone,
            "locale": command.locale,
            "currency": command.currency,
        }
        try:
            async with self._sessions() as session, session.begin():
                row = (
                    await session.execute(
                        text(
                            "SELECT * FROM request_auth.create_self_service_organization("
                            "CAST(:authority AS uuid), CAST(:identity AS uuid), "
                            "CAST(:session AS uuid), CAST(:key AS text), CAST(:intent AS text), "
                            "CAST(:organization AS uuid), CAST(:party AS uuid), "
                            "CAST(:principal AS uuid), CAST(:organization_key AS text), "
                            "CAST(:display_name AS text), CAST(:timezone AS text), "
                            "CAST(:locale AS text), CAST(:currency AS text), "
                            "CAST(:policy AS text), CAST(:correlation AS uuid))"
                        ),
                        {
                            "authority": self._authority,
                            "identity": identity,
                            "session": session_id,
                            "key": key_digest,
                            "intent": hashlib.sha256(
                                json.dumps(intent, sort_keys=True).encode("utf-8")
                            ).hexdigest(),
                            "organization": uuid5(operation, "organization"),
                            "party": uuid5(operation, "party"),
                            "principal": uuid5(operation, "controller"),
                            "organization_key": organization_key,
                            "display_name": command.display_name,
                            "timezone": command.timezone,
                            "locale": command.locale,
                            "currency": command.currency,
                            "policy": command.initial_controller_policy,
                            "correlation": correlation_id,
                        },
                    )
                ).one()
        except DBAPIError as exc:
            _raise_create_error(exc)
        return SelfServiceOrganizationCreated(
            organization_id=UUID(str(row[0])),
            organization_party_id=UUID(str(row[1])),
            controller_principal_id=UUID(str(row[2])),
            controller_binding_id=UUID(str(row[3])),
            membership_id=None if row[4] is None else UUID(str(row[4])),
            organization_key=str(row[5]),
            display_name=str(row[6]),
            default_timezone=str(row[7]),
            default_locale=str(row[8]),
            default_currency=str(row[9]),
            initial_controller_policy=str(row[10]),
            created=bool(row[11]),
            max_organizations=int(row[12]),
            organizations_created=int(row[13]),
            entitlement_id=UUID(str(row[14])),
        )


def _native_subject(authenticated: AuthenticatedHttpSubject) -> tuple[UUID, UUID]:
    subject = authenticated.subject
    if (
        authenticated.authentication_method != "native_session"
        or subject.subject_class is not AuthenticatedSubjectClass.HUMAN
        or subject.metadata.get("recovery_restricted", "").lower() == "true"
        or not authenticated.credential_id
    ):
        raise SelfServiceOrganizationForbidden("a normal native HUMAN session is required")
    try:
        return UUID(subject.subject_id), UUID(authenticated.credential_id)
    except ValueError:
        raise SelfServiceOrganizationForbidden("native session evidence is malformed") from None


def _raise_create_error(exc: DBAPIError) -> Never:
    error_type = _CREATE_ERRORS.get(str(getattr(exc.orig, "sqlstate", "")))
    if error_type is None:
        raise exc
    raise error_type() from None
