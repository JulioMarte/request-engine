from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from request_engine.modules.platform_configuration.application.runtime import (
    ActivePlatformConfiguration,
    ActivePlatformConfigurationResolver,
)
from request_engine.platform.secrets.platform_store import PlatformSecretMetadata


def _active(
    *,
    revision: int,
    binding_revision: int = 1,
    backend_version: int = 1,
    secret_id: UUID | None = None,
) -> ActivePlatformConfiguration:
    resolved_secret_id = secret_id or uuid4()
    return ActivePlatformConfiguration(
        configuration_revision_id=uuid4(),
        configuration_kind="email.delivery",
        provider_kind="smtp",
        revision=revision,
        configuration={
            "host": "smtp.example.test",
            "port": 587,
            "sender": "noreply@example.test",
            "security": "starttls",
            "username": "smtp-user",
        },
        secret_binding_id=uuid4(),
        secret_binding_revision=binding_revision,
        secret_id=resolved_secret_id,
        secret_purpose="email.smtp.password",
        secret_backend="openbao",
        secret_backend_version=backend_version,
        secret_status="active",
    )


class _Source:
    def __init__(self, value: ActivePlatformConfiguration | None) -> None:
        self.value = value
        self.reads = 0

    async def read_active(
        self,
        configuration_kind: str,
    ) -> ActivePlatformConfiguration | None:
        assert configuration_kind == "email.delivery"
        self.reads += 1
        return self.value


class _Store:
    def __init__(self) -> None:
        self.values: dict[UUID, str] = {}
        self.reads = 0

    async def resolve(self, *, secret_id: UUID) -> str:
        self.reads += 1
        return self.values[secret_id]

    async def write(
        self, *, secret_id: UUID, value: str, expected_version: int | None
    ) -> PlatformSecretMetadata:
        raise AssertionError("write not expected")

    async def metadata(self, *, secret_id: UUID) -> PlatformSecretMetadata:
        return PlatformSecretMetadata(
            secret_id=secret_id,
            version=1,
            created_at=datetime.now(UTC),
        )

    async def revoke(self, *, secret_id: UUID) -> None:
        raise AssertionError("revoke not expected")


@pytest.mark.asyncio
async def test_runtime_resolver_caches_then_adopts_new_active_revision() -> None:
    first_secret = uuid4()
    second_secret = uuid4()
    source = _Source(_active(revision=4, secret_id=first_secret))
    store = _Store()
    store.values[first_secret] = "password-v1"
    store.values[second_secret] = "password-v2"
    resolver = ActivePlatformConfigurationResolver(
        source=source,
        secret_store=store,
        poll_interval_seconds=60,
    )

    first = await resolver.resolve_smtp()
    cached = await resolver.resolve_smtp()
    assert first is not None
    assert cached is first
    assert source.reads == 1
    assert store.reads == 1
    assert first.password == "password-v1"

    source.value = _active(revision=5, secret_id=second_secret)
    resolver.invalidate("email.delivery")
    second = await resolver.resolve_smtp()

    assert second is not None
    assert second.active_revision == 5
    assert second.password == "password-v2"
    assert source.reads == 2
    assert store.reads == 2


@pytest.mark.asyncio
async def test_runtime_resolver_secret_rotation_changes_cache_fingerprint() -> None:
    secret_id = uuid4()
    source = _Source(
        _active(
            revision=4,
            binding_revision=1,
            backend_version=1,
            secret_id=secret_id,
        )
    )
    store = _Store()
    store.values[secret_id] = "password-v1"
    resolver = ActivePlatformConfigurationResolver(
        source=source,
        secret_store=store,
        poll_interval_seconds=60,
    )

    first = await resolver.resolve_smtp()
    assert first is not None
    assert first.secret_backend_version == 1

    store.values[secret_id] = "password-v2"
    source.value = _active(
        revision=4,
        binding_revision=2,
        backend_version=2,
        secret_id=secret_id,
    )
    rotated = await resolver.resolve_smtp(force_refresh=True)

    assert rotated is not None
    assert rotated.active_revision == 4
    assert rotated.secret_binding_revision == 2
    assert rotated.secret_backend_version == 2
    assert rotated.password == "password-v2"


@pytest.mark.asyncio
async def test_runtime_resolver_returns_none_when_no_managed_active_revision() -> None:
    resolver = ActivePlatformConfigurationResolver(
        source=_Source(None),
        secret_store=None,
    )
    assert await resolver.resolve_smtp() is None
