"""Transport contract of self-service owner accounts (ADR 0021, INV-SELF-SERVICE-ACCOUNT-001).

Plausible defects: trusted identity fields accepted from the body, tenant selectors
or query strings admitted on pre-tenant operations, untyped error leakage, the
public enrollment escaping the authentication admission budget, or an organization
key/locale/timezone accepted outside the published rules.
"""

import smtplib
from collections.abc import Callable
from dataclasses import replace
from email.message import EmailMessage
from typing import cast
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

from request_engine.entrypoints.http.error_handlers import add_global_error_handlers
from request_engine.modules.tenancy.api.self_service_accounts import (
    install_self_service_account_http,
)
from request_engine.modules.tenancy.application.commands.account_invitations import (
    AccountInvitationEnrollment,
    AccountInvitationInvalid,
    EnrollAccountInvitationCommand,
)
from request_engine.modules.tenancy.application.commands.self_service_organizations import (
    AccountEntitlementView,
    CreateSelfServiceOrganizationCommand,
    SelfServiceOrganizationCreated,
    SelfServiceOrganizationLimitReached,
)
from request_engine.modules.tenancy.domain.account_entitlement import (
    AccountRuleViolation,
    derive_organization_key,
    validate_organization_key,
)
from request_engine.platform.http.request_budget import PUBLIC_CREDENTIAL_PATHS
from request_engine.platform.secrets.delivery import DeliveryOutcome
from request_engine.platform.secrets.smtp_delivery_channel import SmtpRecoveryDeliveryChannel
from request_engine.platform.security.authentication import (
    AuthenticatedSubject,
    AuthenticatedSubjectClass,
)
from request_engine.platform.security.http import AuthenticationRequired
from request_engine.platform.security.subject_http import AuthenticatedHttpSubject

pytestmark = [pytest.mark.unit, pytest.mark.security]
AUTH = {"Authorization": "Bearer verified-test-credential"}


class _Resolver:
    def __init__(self, subject: AuthenticatedSubject) -> None:
        self.subject = subject

    async def resolve_subject(self, request: Request) -> AuthenticatedHttpSubject:
        if request.headers.get("authorization") != AUTH["Authorization"]:
            raise AuthenticationRequired("Bearer required")
        return AuthenticatedHttpSubject(self.subject, "native_session", credential_id=str(uuid4()))


class _Commands:
    def __init__(self) -> None:
        self.created: list[CreateSelfServiceOrganizationCommand] = []
        self.enrolled: list[EnrollAccountInvitationCommand] = []
        self.limit_reached = False

    async def read_entitlement(
        self, authenticated: AuthenticatedHttpSubject
    ) -> AccountEntitlementView | None:
        return AccountEntitlementView(uuid4(), "active", 3, 1, 2)

    async def create_organization(
        self,
        authenticated: AuthenticatedHttpSubject,
        command: CreateSelfServiceOrganizationCommand,
        *,
        correlation_id: UUID | None = None,
    ) -> SelfServiceOrganizationCreated:
        if self.limit_reached:
            raise SelfServiceOrganizationLimitReached()
        self.created.append(command)
        return SelfServiceOrganizationCreated(
            organization_id=uuid4(),
            organization_party_id=uuid4(),
            controller_principal_id=uuid4(),
            controller_binding_id=uuid4(),
            membership_id=uuid4(),
            organization_key="clinica-abc123",
            display_name=command.display_name,
            default_timezone=command.timezone,
            default_locale=command.locale,
            default_currency=command.currency,
            initial_controller_policy=command.initial_controller_policy,
            created=True,
            max_organizations=3,
            organizations_created=2,
            entitlement_id=uuid4(),
        )

    async def enroll(self, command: EnrollAccountInvitationCommand) -> AccountInvitationEnrollment:
        if command.raw_token.startswith("bad"):
            raise AccountInvitationInvalid()
        self.enrolled.append(command)
        return AccountInvitationEnrollment(uuid4(), uuid4(), command.login_handle, uuid4(), 3)


def _app(commands: _Commands) -> FastAPI:
    app = FastAPI()
    add_global_error_handlers(app)
    subject = AuthenticatedSubject(str(uuid4()), str(uuid4()), AuthenticatedSubjectClass.HUMAN)
    install_self_service_account_http(
        app, commands=commands, enrollment=commands, subject_resolver=_Resolver(subject)
    )
    return app


@pytest.mark.asyncio
async def test_pre_tenant_operations_reject_selectors_and_trusted_fields() -> None:
    commands = _Commands()
    async with AsyncClient(
        transport=ASGITransport(app=_app(commands)), base_url="https://test"
    ) as client:
        body = {"display_name": "Clínica Sonrisa"}
        headers = {**AUTH, "Idempotency-Key": "k1"}
        assert (
            await client.post("/v1/me/organizations", headers=AUTH, json=body)
        ).status_code == 422
        unauthenticated = await client.post(
            "/v1/me/organizations", headers={"Idempotency-Key": "k1"}, json=body
        )
        assert unauthenticated.status_code == 401
        selector = await client.post(
            "/v1/me/organizations",
            headers={**headers, "X-RE-Organization-ID": str(uuid4())},
            json=body,
        )
        assert selector.status_code == 400
        assert (
            await client.post("/v1/me/organizations?principal_id=x", headers=headers, json=body)
        ).status_code == 400
        for injected in ({"organization_id": str(uuid4())}, {"principal_id": str(uuid4())}):
            assert (
                await client.post("/v1/me/organizations", headers=headers, json=body | injected)
            ).status_code == 422
        bad_zone = await client.post(
            "/v1/me/organizations", headers=headers, json=body | {"timezone": "Mars/Base"}
        )
        assert bad_zone.status_code == 422
        assert bad_zone.json()["error"]["code"] == "account_organization_invalid"
        created = await client.post("/v1/me/organizations", headers=headers, json=body)
        assert created.status_code == 201 and created.headers["cache-control"] == "no-store"
        assert created.json()["organization_creation"]["remaining"] == 1
        assert commands.created[0].timezone == "America/Santo_Domingo"
        assert (commands.created[0].locale, commands.created[0].currency) == ("es-DO", "DOP")
        commands.limit_reached = True
        limited = await client.post("/v1/me/organizations", headers=headers, json=body)
        assert limited.status_code == 409
        assert limited.json()["error"] == {
            "code": "account_organization_limit_reached",
            "message": "The self-service account operation could not be accepted.",
            "resolution": "request_authority",
            "retryable": False,
        } | {key: value for key, value in limited.json()["error"].items() if key == "details"}
        account = await client.get("/v1/me/account", headers=AUTH)
        assert account.json()["organization_creation"]["remaining"] == 2


@pytest.mark.asyncio
async def test_public_enrollment_is_body_only_and_typed() -> None:
    commands = _Commands()
    async with AsyncClient(
        transport=ASGITransport(app=_app(commands)), base_url="https://test"
    ) as client:
        body = {"invitation_token": "t" * 43, "login_handle": " Me@X.Test ", "password": "p" * 12}
        assert (
            await client.post("/v1/account-invitations:enroll?token=leak", json=body)
        ).status_code == 400
        bad = await client.post(
            "/v1/account-invitations:enroll", json=body | {"invitation_token": "bad" + "x" * 40}
        )
        assert bad.status_code == 422
        assert bad.json()["error"]["code"] == "account_invitation_invalid"
        assert (
            await client.post("/v1/account-invitations:enroll", json=body | {"max": 9})
        ).status_code == 422
        ok = await client.post("/v1/account-invitations:enroll", json=body)
        assert ok.status_code == 201 and ok.json()["login_handle"] == "me@x.test"
    assert "/v1/account-invitations:enroll" in PUBLIC_CREDENTIAL_PATHS


def test_organization_key_rules_are_deterministic_and_closed() -> None:
    assert derive_organization_key("Clínica Dental Sonrisa", "a1b2c3") == (
        "clinica-dental-sonrisa-a1b2c3"
    )
    assert derive_organization_key("¡¡!!", "a1b2c3") == "negocio-a1b2c3"
    for invalid in ("ab", "Upper", "double--hyphen", "-edge", "x" * 64):
        with pytest.raises(AccountRuleViolation):
            validate_organization_key(invalid)
    with pytest.raises(ValueError):
        replace(
            CreateSelfServiceOrganizationCommand(display_name="X", idempotency_key="k"),
            locale="spanish",
        )


class _FakeSmtp:
    sent: list[EmailMessage] = []

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        pass

    def __enter__(self) -> "_FakeSmtp":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def ehlo(self) -> None:
        return None

    def starttls(self, **_kwargs: object) -> None:
        return None

    def send_message(self, message: EmailMessage) -> None:
        _FakeSmtp.sent.append(message)


@pytest.mark.asyncio
async def test_account_invitation_email_carries_link_in_fragment_only() -> None:
    channel = SmtpRecoveryDeliveryChannel(
        host="smtp.example.test",
        port=587,
        sender="no-reply@example.test",
        reset_url="https://app.example.test/account-invitations",
        purpose="account_invitation",
        transport=cast(Callable[..., smtplib.SMTP], _FakeSmtp),
    )
    outcome = await channel.send(
        secret="secret-token_value",
        destination_reference="owner@example.test",
        idempotency_key="account-invitation:1",
    )
    assert outcome is DeliveryOutcome.DELIVERED
    body = str(_FakeSmtp.sent[-1].get_content())
    assert "https://app.example.test/account-invitations#token=secret-token_value" in body
    assert "?" not in body.split("#token=")[0].rsplit("\n", 1)[-1]
    with pytest.raises(ValueError):
        SmtpRecoveryDeliveryChannel(
            host="smtp.example.test",
            port=587,
            sender="no-reply@example.test",
            purpose="account_invitation",
        )
