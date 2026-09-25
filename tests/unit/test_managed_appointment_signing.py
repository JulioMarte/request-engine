from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from request_engine.modules.booking.adapters.appointment_signing_reference import (
    ActiveAppointmentSigningReference,
)
from request_engine.modules.booking.adapters.managed_appointment_signing import (
    AppointmentSigningKeyringUnavailable,
    ManagedAppointmentSigningKeyringResolver,
)
from request_engine.platform.security.appointment_option_keyring import (
    create_appointment_option_keyring,
)
from request_engine.platform.secrets.platform_store import (
    PlatformSecretMetadata,
    PlatformSecretNotFound,
)

pytestmark = pytest.mark.unit


class _Source:
    def __init__(self, reference: ActiveAppointmentSigningReference | None) -> None:
        self.reference = reference
        self.reads = 0

    async def read_active(self) -> ActiveAppointmentSigningReference | None:
        self.reads += 1
        return self.reference


class _Store:
    def __init__(self, values: dict[UUID, str]) -> None:
        self.values = values
        self.resolves: list[UUID] = []

    async def resolve(self, *, secret_id: UUID) -> str:
        self.resolves.append(secret_id)
        try:
            return self.values[secret_id]
        except KeyError as exc:
            raise PlatformSecretNotFound() from exc

    async def write(
        self,
        *,
        secret_id: UUID,
        value: str,
        expected_version: int | None,
        operation_id: UUID | None = None,
    ) -> PlatformSecretMetadata:
        raise AssertionError("runtime signing store must be read-only")

    async def metadata(self, *, secret_id: UUID) -> PlatformSecretMetadata:
        raise AssertionError("runtime signing resolver must not need metadata reads")

    async def revoke(self, *, secret_id: UUID) -> None:
        raise AssertionError("runtime signing store must be read-only")


def _reference(
    secret_id: UUID,
    *,
    configuration_revision: int,
    binding_revision: int,
    backend_version: int,
) -> ActiveAppointmentSigningReference:
    return ActiveAppointmentSigningReference(
        configuration_revision=configuration_revision,
        secret_binding_revision=binding_revision,
        secret_id=secret_id,
        secret_backend_version=backend_version,
    )


@pytest.mark.asyncio
async def test_managed_signing_resolver_reloads_when_authoritative_fingerprint_changes() -> None:
    first_id = uuid4()
    second_id = uuid4()
    source = _Source(
        _reference(
            first_id,
            configuration_revision=1,
            binding_revision=1,
            backend_version=1,
        )
    )
    store = _Store(
        {
            first_id: create_appointment_option_keyring(
                "k1",
                key=b"appointment-managed-key-one-000000000000001",
            ),
            second_id: create_appointment_option_keyring(
                "k2",
                key=b"appointment-managed-key-two-000000000000002",
            ),
        }
    )
    resolver = ManagedAppointmentSigningKeyringResolver(
        source=source,
        secret_store=store,
        poll_interval_seconds=5,
    )

    first = await resolver.resolve(force_refresh=True)
    assert first is not None
    assert first.active_key_id == "k1"

    source.reference = _reference(
        second_id,
        configuration_revision=2,
        binding_revision=2,
        backend_version=2,
    )
    second = await resolver.resolve(force_refresh=True)

    assert second is not None
    assert second.active_key_id == "k2"
    assert store.resolves == [first_id, second_id]


@pytest.mark.asyncio
async def test_managed_signing_resolver_fails_closed_on_invalid_secret_payload() -> None:
    secret_id = uuid4()
    source = _Source(
        _reference(
            secret_id,
            configuration_revision=1,
            binding_revision=1,
            backend_version=1,
        )
    )
    resolver = ManagedAppointmentSigningKeyringResolver(
        source=source,
        secret_store=_Store({secret_id: "not-json"}),
    )

    with pytest.raises(AppointmentSigningKeyringUnavailable):
        await resolver.resolve(force_refresh=True)


@pytest.mark.asyncio
async def test_managed_signing_resolver_returns_none_when_no_active_configuration() -> None:
    source = _Source(None)
    resolver = ManagedAppointmentSigningKeyringResolver(
        source=source,
        secret_store=_Store({}),
    )

    assert await resolver.resolve(force_refresh=True) is None
