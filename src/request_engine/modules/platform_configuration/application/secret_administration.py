from __future__ import annotations

from request_engine.modules.platform_configuration.application.secrets import (
    CreatePlatformSecret,
    PlatformSecretConflict,
    PlatformSecretMutationStore,
    PlatformSecretReconciliationRequired,
    PlatformSecretUnavailable,
    RevokePlatformSecret,
    RotatePlatformSecret,
    SecretMutationOperation,
    SecretMutationResult,
)
from request_engine.platform.secrets.platform_store import (
    PlatformSecretConflict as StoreSecretConflict,
)
from request_engine.platform.secrets.platform_store import (
    PlatformSecretMetadata,
    PlatformSecretNotFound,
    PlatformSecretStore,
    PlatformSecretStoreUnavailable,
)
from request_engine.platform.security.platform_context import PlatformActorContext

StoreSecretNotFound = PlatformSecretNotFound



class PlatformSecretAdministrationService:
    """Coordinate PostgreSQL authority with an external secret store.

    Every database call is its own transaction. Backend network I/O happens only
    between those transactions, so no authoritative PostgreSQL lock is held
    while OpenBao or another secret backend is contacted.
    """

    def __init__(
        self,
        *,
        mutations: PlatformSecretMutationStore,
        store: PlatformSecretStore,
    ) -> None:
        self._mutations = mutations
        self._store = store

    async def create(
        self,
        actor: PlatformActorContext,
        command: CreatePlatformSecret,
    ) -> SecretMutationResult:
        operation = await self._mutations.prepare_create(actor, command)
        operation = await self._resume_write(
            actor,
            operation,
            value=command.value,
            expected_version=None,
        )
        return _result(operation)

    async def rotate(
        self,
        actor: PlatformActorContext,
        command: RotatePlatformSecret,
    ) -> SecretMutationResult:
        operation = await self._mutations.prepare_rotate(actor, command)
        operation = await self._resume_write(
            actor,
            operation,
            value=command.value,
            expected_version=command.expected_backend_version,
        )
        return _result(operation)

    async def revoke(
        self,
        actor: PlatformActorContext,
        command: RevokePlatformSecret,
    ) -> SecretMutationResult:
        operation = await self._mutations.prepare_revoke(actor, command)
        operation = await self._resume_revoke(actor, operation)
        return _result(operation)

    async def _resume_write(
        self,
        actor: PlatformActorContext,
        operation: SecretMutationOperation,
        *,
        value: str,
        expected_version: int | None,
    ) -> SecretMutationOperation:
        terminal = _terminal(operation)
        if terminal is not None:
            return terminal
        if operation.state == "backend_applied":
            return await self._commit(actor, operation)
        if operation.state != "prepared":
            raise PlatformSecretReconciliationRequired()

        try:
            metadata = await self._store.write(
                secret_id=operation.secret_id,
                value=value,
                expected_version=expected_version,
                operation_id=operation.operation_id,
            )
        except StoreSecretConflict:
            metadata = await self._recover_ambiguous_write(operation, conflict=True)
        except PlatformSecretStoreUnavailable:
            metadata = await self._recover_ambiguous_write(operation, conflict=False)

        if metadata.operation_id != operation.operation_id:
            raise PlatformSecretConflict()
        if expected_version is not None and metadata.version <= expected_version:
            raise PlatformSecretConflict()

        operation = await self._mutations.mark_backend_applied(
            actor,
            operation.operation_id,
            metadata.version,
        )
        return await self._commit(actor, operation)

    async def _recover_ambiguous_write(
        self,
        operation: SecretMutationOperation,
        *,
        conflict: bool,
    ) -> PlatformSecretMetadata:
        try:
            metadata = await self._store.metadata(secret_id=operation.secret_id)
        except (StoreSecretNotFound, PlatformSecretStoreUnavailable):
            if conflict:
                raise PlatformSecretConflict() from None
            raise PlatformSecretUnavailable() from None
        if metadata.operation_id != operation.operation_id:
            if conflict:
                raise PlatformSecretConflict()
            raise PlatformSecretUnavailable()
        return metadata

    async def _resume_revoke(
        self,
        actor: PlatformActorContext,
        operation: SecretMutationOperation,
    ) -> SecretMutationOperation:
        terminal = _terminal(operation)
        if terminal is not None:
            return terminal
        if operation.state == "backend_applied":
            return await self._commit(actor, operation)
        if operation.state != "prepared" or operation.expected_backend_version is None:
            raise PlatformSecretReconciliationRequired()

        expected_version = operation.expected_backend_version
        try:
            metadata = await self._store.metadata(secret_id=operation.secret_id)
        except StoreSecretNotFound:
            operation = await self._mutations.mark_backend_applied(
                actor,
                operation.operation_id,
                expected_version,
            )
            return await self._commit(actor, operation)
        except PlatformSecretStoreUnavailable:
            raise PlatformSecretUnavailable() from None

        if metadata.version != expected_version:
            raise PlatformSecretConflict()

        try:
            await self._store.revoke(secret_id=operation.secret_id)
        except PlatformSecretStoreUnavailable:
            try:
                await self._store.metadata(secret_id=operation.secret_id)
            except StoreSecretNotFound:
                pass
            except PlatformSecretStoreUnavailable:
                raise PlatformSecretUnavailable() from None
            else:
                raise PlatformSecretUnavailable() from None

        operation = await self._mutations.mark_backend_applied(
            actor,
            operation.operation_id,
            expected_version,
        )
        return await self._commit(actor, operation)

    async def _commit(
        self,
        actor: PlatformActorContext,
        operation: SecretMutationOperation,
    ) -> SecretMutationOperation:
        committed = await self._mutations.commit(actor, operation.operation_id)
        terminal = _terminal(committed)
        if terminal is None:
            raise PlatformSecretReconciliationRequired()
        return terminal


def _terminal(operation: SecretMutationOperation) -> SecretMutationOperation | None:
    if operation.state == "reconcile_required":
        raise PlatformSecretReconciliationRequired()
    if operation.state == "committed":
        return operation
    return None


def _result(operation: SecretMutationOperation) -> SecretMutationResult:
    if (
        operation.state != "committed"
        or operation.result_binding_id is None
        or operation.result_binding_revision is None
        or operation.result_binding_status is None
        or operation.applied_backend_version is None
    ):
        raise PlatformSecretReconciliationRequired()
    return SecretMutationResult(
        binding_id=operation.result_binding_id,
        revision=operation.result_binding_revision,
        backend_version=operation.applied_backend_version,
        status=operation.result_binding_status,
    )
