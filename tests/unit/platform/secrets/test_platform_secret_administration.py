from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from request_engine.modules.platform_configuration.application.secret_administration import (
    PlatformSecretAdministrationService,
)
from request_engine.modules.platform_configuration.application.secrets import (
    CreatePlatformSecret,
    PlatformSecretConflict,
    PlatformSecretReconciliationRequired,
    RevokePlatformSecret,
    RotatePlatformSecret,
    SecretMutationOperation,
)
from request_engine.platform.secrets.platform_store import (
    PlatformSecretConflict as StoreSecretConflict,
)
from request_engine.platform.secrets.platform_store import (
    PlatformSecretMetadata,
    PlatformSecretNotFound,
)
from request_engine.platform.security.assurance import AuthenticationAssurance
from request_engine.platform.security.context import PrincipalKind
from request_engine.platform.security.platform_context import PlatformActorContext

pytestmark = pytest.mark.unit


def _actor() -> PlatformActorContext:
    return PlatformActorContext(
        principal_id=uuid4(),
        capabilities=frozenset(
            {
                "platform.secret.write",
                "platform.secret.rotate",
                "platform.secret.revoke",
            }
        ),
        authority_revision=1,
        principal_kind=PrincipalKind.HUMAN,
        authentication_method="webauthn",
        authentication_assurance=AuthenticationAssurance.PHISHING_RESISTANT,
        user_verified=True,
        authenticated_at=datetime.now(UTC),
    )


class FakeMutations:
    def __init__(self, operation: SecretMutationOperation) -> None:
        self.operation = operation
        self.marked_versions: list[int] = []
        self.commit_to_reconcile = False

    async def prepare_create(
        self, actor: PlatformActorContext, command: CreatePlatformSecret
    ) -> SecretMutationOperation:
        return self.operation

    async def prepare_rotate(
        self, actor: PlatformActorContext, command: RotatePlatformSecret
    ) -> SecretMutationOperation:
        return self.operation

    async def prepare_revoke(
        self, actor: PlatformActorContext, command: RevokePlatformSecret
    ) -> SecretMutationOperation:
        return self.operation

    async def mark_backend_applied(
        self,
        actor: PlatformActorContext,
        operation_id: UUID,
        backend_version: int,
    ) -> SecretMutationOperation:
        self.marked_versions.append(backend_version)
        self.operation = replace(
            self.operation,
            applied_backend_version=backend_version,
            state="backend_applied",
        )
        return self.operation

    async def commit(
        self,
        actor: PlatformActorContext,
        operation_id: UUID,
    ) -> SecretMutationOperation:
        if self.commit_to_reconcile:
            self.operation = replace(self.operation, state="reconcile_required")
            return self.operation
        self.operation = replace(
            self.operation,
            state="committed",
            result_binding_id=self.operation.binding_id or uuid4(),
            result_binding_revision=(
                1
                if self.operation.expected_binding_revision is None
                else self.operation.expected_binding_revision + 1
            ),
            result_binding_status=(
                "revoked" if self.operation.operation_kind == "revoke" else "active"
            ),
        )
        return self.operation


class FakeStore:
    def __init__(self) -> None:
        self.write_conflict = False
        self.metadata_value: PlatformSecretMetadata | None = None
        self.writes: list[tuple[UUID, str, int | None, UUID | None]] = []
        self.revoked: list[UUID] = []

    async def write(
        self,
        *,
        secret_id: UUID,
        value: str,
        expected_version: int | None,
        operation_id: UUID | None = None,
    ) -> PlatformSecretMetadata:
        self.writes.append((secret_id, value, expected_version, operation_id))
        if self.write_conflict:
            raise StoreSecretConflict()
        version = 1 if expected_version is None else expected_version + 1
        return PlatformSecretMetadata(
            secret_id=secret_id,
            version=version,
            operation_id=operation_id,
        )

    async def resolve(self, *, secret_id: UUID) -> str:
        raise AssertionError("admin orchestration must never resolve plaintext")

    async def metadata(self, *, secret_id: UUID) -> PlatformSecretMetadata:
        if self.metadata_value is None:
            raise PlatformSecretNotFound()
        return self.metadata_value

    async def revoke(self, *, secret_id: UUID) -> None:
        self.revoked.append(secret_id)


def _operation(
    kind: str,
    *,
    expected_revision: int | None = None,
    expected_backend_version: int | None = None,
) -> SecretMutationOperation:
    return SecretMutationOperation(
        operation_id=uuid4(),
        operation_kind=kind,
        binding_id=None if kind == "create" else uuid4(),
        secret_id=uuid4(),
        purpose="email.smtp.password",
        backend="openbao",
        expected_binding_revision=expected_revision,
        expected_backend_version=expected_backend_version,
        applied_backend_version=None,
        state="prepared",
        result_binding_id=None,
        result_binding_revision=None,
        result_binding_status=None,
    )


@pytest.mark.asyncio
async def test_create_keeps_plaintext_outside_durable_mutation_state() -> None:
    operation = _operation("create")
    mutations = FakeMutations(operation)
    store = FakeStore()
    service = PlatformSecretAdministrationService(mutations=mutations, store=store)

    result = await service.create(
        _actor(),
        CreatePlatformSecret(
            purpose="email.smtp.password",
            backend="openbao",
            value="sentinel-plaintext",
            idempotency_key="create-1",
        ),
    )

    assert store.writes == [
        (operation.secret_id, "sentinel-plaintext", None, operation.operation_id)
    ]
    assert mutations.marked_versions == [1]
    assert result.backend_version == 1
    assert result.status == "active"
    assert "sentinel-plaintext" not in repr(mutations.operation)


@pytest.mark.asyncio
async def test_rotation_recovers_ambiguous_prior_write_only_with_same_marker() -> None:
    operation = _operation("rotate", expected_revision=4, expected_backend_version=7)
    mutations = FakeMutations(operation)
    store = FakeStore()
    store.write_conflict = True
    store.metadata_value = PlatformSecretMetadata(
        secret_id=operation.secret_id,
        version=8,
        operation_id=operation.operation_id,
    )
    service = PlatformSecretAdministrationService(mutations=mutations, store=store)

    result = await service.rotate(
        _actor(),
        RotatePlatformSecret(
            binding_id=operation.binding_id or uuid4(),
            expected_revision=4,
            expected_backend_version=7,
            value="rotated-secret",
            idempotency_key="rotate-1",
        ),
    )

    assert mutations.marked_versions == [8]
    assert result.backend_version == 8


@pytest.mark.asyncio
async def test_rotation_rejects_cas_conflict_owned_by_different_operation() -> None:
    operation = _operation("rotate", expected_revision=4, expected_backend_version=7)
    mutations = FakeMutations(operation)
    store = FakeStore()
    store.write_conflict = True
    store.metadata_value = PlatformSecretMetadata(
        secret_id=operation.secret_id,
        version=8,
        operation_id=uuid4(),
    )
    service = PlatformSecretAdministrationService(mutations=mutations, store=store)

    with pytest.raises(PlatformSecretConflict):
        await service.rotate(
            _actor(),
            RotatePlatformSecret(
                binding_id=operation.binding_id or uuid4(),
                expected_revision=4,
                expected_backend_version=7,
                value="rotated-secret",
                idempotency_key="rotate-2",
            ),
        )


@pytest.mark.asyncio
async def test_backend_success_plus_db_cas_loss_is_operator_visible() -> None:
    operation = _operation("rotate", expected_revision=4, expected_backend_version=7)
    mutations = FakeMutations(operation)
    mutations.commit_to_reconcile = True
    store = FakeStore()
    service = PlatformSecretAdministrationService(mutations=mutations, store=store)

    with pytest.raises(PlatformSecretReconciliationRequired):
        await service.rotate(
            _actor(),
            RotatePlatformSecret(
                binding_id=operation.binding_id or uuid4(),
                expected_revision=4,
                expected_backend_version=7,
                value="rotated-secret",
                idempotency_key="rotate-3",
            ),
        )

    assert mutations.operation.state == "reconcile_required"
    assert mutations.operation.applied_backend_version == 8


@pytest.mark.asyncio
async def test_revoke_reconciles_backend_already_absent_to_revoked_metadata() -> None:
    operation = _operation("revoke", expected_revision=2, expected_backend_version=5)
    mutations = FakeMutations(operation)
    store = FakeStore()
    service = PlatformSecretAdministrationService(mutations=mutations, store=store)

    result = await service.revoke(
        _actor(),
        RevokePlatformSecret(
            binding_id=operation.binding_id or uuid4(),
            expected_revision=2,
            expected_backend_version=5,
            idempotency_key="revoke-1",
        ),
    )

    assert store.revoked == []
    assert mutations.marked_versions == [5]
    assert result.status == "revoked"
