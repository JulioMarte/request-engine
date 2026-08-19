import asyncio

from request_engine.modules.delivery.contracts.access import (
    ProvisionAccessRequest,
    ProvisionedAccess,
    RevokeAccessRequest,
)


class RecordingProvider:
    """In-memory provider with semantic-idempotency and reconciliation behavior."""

    def __init__(
        self,
        *,
        provision_failures: int = 0,
        revoke_failures: int = 0,
    ) -> None:
        self.provision_calls = 0
        self.created_resources = 0
        self.lookup_calls = 0
        self.revoke_calls = 0
        self.provision_failures = provision_failures
        self.revoke_failures = revoke_failures
        self.idempotency_keys: list[str] = []
        self.resources: dict[str, ProvisionedAccess] = {}
        self.revoked_keys: set[str] = set()

    async def provision(self, request: ProvisionAccessRequest) -> ProvisionedAccess:
        self.provision_calls += 1
        self.idempotency_keys.append(request.materialization_key)
        if self.provision_failures:
            self.provision_failures -= 1
            raise RuntimeError("provider provisioning unavailable")
        existing = self.resources.get(request.materialization_key)
        if existing is not None:
            return existing

        slug = request.materialization_key.replace(":", "-")
        materialized = ProvisionedAccess(
            f"https://meet.example/join/{slug}",
            f"ext-{slug}",
            {},
        )
        self.resources[request.materialization_key] = materialized
        self.created_resources += 1
        return materialized

    async def lookup(self, *, materialization_key: str) -> ProvisionedAccess | None:
        self.lookup_calls += 1
        if materialization_key in self.revoked_keys:
            return None
        return self.resources.get(materialization_key)

    async def revoke(self, request: RevokeAccessRequest) -> None:
        self.revoke_calls += 1
        if self.revoke_failures:
            self.revoke_failures -= 1
            raise RuntimeError("provider revocation unavailable")
        self.revoked_keys.add(request.materialization_key)


class RacingProvider(RecordingProvider):
    def __init__(self) -> None:
        super().__init__()
        self.provision_started = asyncio.Event()
        self.release_provision = asyncio.Event()

    async def provision(self, request: ProvisionAccessRequest) -> ProvisionedAccess:
        self.provision_calls += 1
        self.idempotency_keys.append(request.materialization_key)
        if self.provision_failures:
            self.provision_failures -= 1
            raise RuntimeError("provider provisioning unavailable")
        existing = self.resources.get(request.materialization_key)
        if existing is not None:
            return existing

        self.provision_started.set()
        await asyncio.wait_for(self.release_provision.wait(), timeout=10)
        slug = request.materialization_key.replace(":", "-")
        materialized = ProvisionedAccess(
            f"https://meet.example/join/{slug}",
            f"ext-{slug}",
            {},
        )
        existing = self.resources.setdefault(request.materialization_key, materialized)
        if existing is materialized:
            self.created_resources += 1
        return existing
