from contextlib import contextmanager
from typing import Iterator
from uuid import UUID, uuid4

from request_engine.modules.tenancy.adapters.db.identity_exchange_adopt import (
    PostgresPortableIdentityAdopter,
)
from request_engine.modules.tenancy.adapters.db.identity_exchange_match import (
    PostgresPortableIdentityMatcher,
)
from request_engine.modules.tenancy.adapters.db.identity_exchange_publish import (
    PostgresPortableProfilePublisher,
)
from request_engine.modules.tenancy.application.identity_exchange import (
    AdoptPortableIdentityCommand,
    MatchPortableIdentityCommand,
    PublishPortableProfileCommand,
)
from request_engine.modules.tenancy.contracts.party_registry import PartySourceKind
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext, PrincipalKind
from request_engine.platform.security.execution_context import bind_actor_context, reset_actor_context

KEY = b"integration-identity-exchange-key-32-bytes-minimum"
PROOF = "operator_document_witness"
CEDULA = "40212345678"
PASSPORT = "SC1234567"


@contextmanager
def operator_actor(organization_id: UUID, principal_id: UUID) -> Iterator[None]:
    token = bind_actor_context(
        ActorContext(
            organization_id=organization_id,
            principal_id=principal_id,
            capabilities=frozenset(
                {
                    "identity_exchange.publish",
                    "identity_exchange.match",
                    "identity_exchange.adopt",
                }
            ),
            principal_kind=PrincipalKind.HUMAN,
            authentication_method="integration_test",
            platform="reception_web",
        )
    )
    try:
        yield
    finally:
        reset_actor_context(token)


def adapters(session_factory: SessionFactory) -> tuple[
    PostgresPortableProfilePublisher,
    PostgresPortableIdentityMatcher,
    PostgresPortableIdentityAdopter,
]:
    return (
        PostgresPortableProfilePublisher(session_factory, KEY),
        PostgresPortableIdentityMatcher(session_factory, KEY),
        PostgresPortableIdentityAdopter(session_factory, KEY),
    )


def publish_command(
    org: UUID,
    principal: UUID,
    party: UUID,
    *,
    kind: str = "cedula",
    authority: str | None = None,
) -> PublishPortableProfileCommand:
    return PublishPortableProfileCommand(
        organization_id=org,
        principal_id=principal,
        party_id=party,
        document_kind=kind,
        document_authority=authority,
        consented_fields=("display_name", "phone", "insurance_member"),
        proof_kind=PROOF,
        idempotency_key=f"publish-{uuid4().hex}",
        source_kind=PartySourceKind.OPERATOR,
        platform="reception_web",
    )


def match_command(
    org: UUID,
    principal: UUID,
    value: str = CEDULA,
    *,
    kind: str = "cedula",
    authority: str | None = None,
) -> MatchPortableIdentityCommand:
    return MatchPortableIdentityCommand(
        organization_id=org,
        principal_id=principal,
        document_kind=kind,
        document_authority=authority,
        document_value=value,
        proof_kind=PROOF,
        idempotency_key=f"match-{uuid4().hex}",
    )


def adopt_command(
    org: UUID,
    principal: UUID,
    candidate: UUID,
    *,
    value: str = CEDULA,
    kind: str = "cedula",
    authority: str | None = None,
    key: str | None = None,
) -> AdoptPortableIdentityCommand:
    return AdoptPortableIdentityCommand(
        organization_id=org,
        principal_id=principal,
        candidate_ref=candidate,
        document_kind=kind,
        document_authority=authority,
        document_value=value,
        consented_fields=("display_name", "phone", "insurance_member"),
        proof_kind=PROOF,
        idempotency_key=key or f"adopt-{uuid4().hex}",
        source_kind=PartySourceKind.OPERATOR,
        platform="reception_web",
    )
