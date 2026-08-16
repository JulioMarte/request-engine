from collections.abc import Mapping
from uuid import UUID

from request_engine.modules.delivery.contracts.access import (
    AccessPolicy,
    AccessStatus,
    DeliveryPolicyReader,
    DeliveryWorkClaim,
    ProvisionAccessRequest,
    ProvisionedAccess,
    ProvisioningMode,
    ReservationAccess,
    ReservationAccessProvider,
    ReservationAccessRepository,
    ReservationAccessSource,
    RevokeAccessRequest,
)


class UnknownAccessProviderError(LookupError):
    pass


class ReservationAccessService:
    """Converge provider access to the current Reservation revision.

    Provider I/O always occurs outside authoritative DB transactions. A stable
    materialization key makes provisioning replay-safe; READY/REVOKED authority
    is published only through repository methods fenced by the current Outbox
    claim.
    """

    def __init__(
        self,
        policy_reader: DeliveryPolicyReader,
        repository: ReservationAccessRepository,
        providers: Mapping[str, ReservationAccessProvider],
    ) -> None:
        self._policy_reader = policy_reader
        self._repository = repository
        self._providers = providers

    async def reconcile_reservation_access(
        self,
        source: ReservationAccessSource,
        *,
        work_claim: DeliveryWorkClaim,
    ) -> tuple[ReservationAccess, ...]:
        self._validate_claim_tenant(source.organization_id, work_claim)
        if source.status != "confirmed":
            return await self.revoke_reservation_access(
                source.organization_id,
                source.reservation_id,
                work_claim=work_claim,
            )
        if not await self._repository.confirmed_source_is_current(source, work_claim):
            return ()

        policies = await self._policy_reader.get_access_policies(
            source.organization_id, source.offering_version_id
        )
        desired = {
            policy.access_key: policy
            for policy in policies
            if policy.provisioning_mode is ProvisioningMode.IMMEDIATE
        }

        active = await self._repository.list_unrevoked_for_reservation(
            source.organization_id, source.reservation_id
        )
        for access in active:
            policy = desired.get(access.access_key)
            if access.reservation_revision > source.revision:
                continue
            if (
                access.reservation_revision < source.revision
                or policy is None
                or access.kind is not policy.kind
                or access.provider_key != policy.provider_key
            ):
                await self._revoke_one(access, work_claim)

        ready: list[ReservationAccess] = []
        for policy in desired.values():
            claim = await self._repository.ensure_pending(source, policy, work_claim)
            if claim is None or claim.status is AccessStatus.REVOKED:
                continue
            if claim.status is AccessStatus.READY:
                ready.append(claim)
                continue

            recorded = claim
            if claim.provisioned_at is None:
                materialized = await self._materialize(source, policy)
                recorded = await self._repository.record_materialized(claim, materialized)
                if recorded.status is AccessStatus.REVOKED:
                    await self._revoke_materialized_result(recorded, materialized)
                    continue
                if recorded.status is AccessStatus.READY:
                    ready.append(recorded)
                    continue

            published = await self._repository.publish_ready_if_current(
                source, recorded, work_claim
            )
            if published is not None:
                if published.status is AccessStatus.READY:
                    ready.append(published)
                continue

            current = await self._repository.get_by_key(
                source.organization_id,
                source.reservation_id,
                source.revision,
                policy.access_key,
            )
            if current is not None and current.status is not AccessStatus.REVOKED:
                await self._revoke_one(current, work_claim)

        return tuple(ready)

    async def revoke_reservation_access(
        self,
        organization_id: UUID,
        reservation_id: UUID,
        *,
        work_claim: DeliveryWorkClaim,
    ) -> tuple[ReservationAccess, ...]:
        self._validate_claim_tenant(organization_id, work_claim)
        active = await self._repository.list_unrevoked_for_reservation(
            organization_id, reservation_id
        )
        revoked: list[ReservationAccess] = []
        for access in active:
            revoked.append(await self._revoke_one(access, work_claim))
        return tuple(revoked)

    async def _revoke_one(
        self,
        access: ReservationAccess,
        work_claim: DeliveryWorkClaim,
    ) -> ReservationAccess:
        if access.provider_key is not None:
            provider = self._provider(access.provider_key)
            materialized = (
                ProvisionedAccess(
                    access.access_uri,
                    access.external_ref,
                    access.public_data,
                )
                if access.provisioned_at is not None
                else await provider.lookup(materialization_key=access.materialization_key)
            )
            if materialized is not None:
                await provider.revoke(self._revoke_request(access, materialized))
        return await self._repository.mark_revoked_if_current(access, work_claim)

    async def _revoke_materialized_result(
        self,
        access: ReservationAccess,
        materialized: ProvisionedAccess,
    ) -> None:
        if access.provider_key is None:
            return
        provider = self._provider(access.provider_key)
        await provider.revoke(self._revoke_request(access, materialized))

    async def _materialize(
        self, source: ReservationAccessSource, policy: AccessPolicy
    ) -> ProvisionedAccess:
        materialization_key = self._materialization_key(source, policy)
        if policy.provider_key is None:
            return ProvisionedAccess(None, None, policy.public_data)
        provider = self._provider(policy.provider_key)
        result = await provider.provision(
            ProvisionAccessRequest(
                source=source,
                access_key=policy.access_key,
                kind=policy.kind,
                public_data=policy.public_data,
                materialization_key=materialization_key,
            )
        )
        return ProvisionedAccess(
            result.access_uri,
            result.external_ref,
            {**policy.public_data, **result.public_data},
        )

    def _provider(self, provider_key: str) -> ReservationAccessProvider:
        provider = self._providers.get(provider_key)
        if provider is None:
            raise UnknownAccessProviderError(provider_key)
        return provider

    @staticmethod
    def _materialization_key(
        source: ReservationAccessSource, policy: AccessPolicy
    ) -> str:
        return (
            f"reservation-access:{source.reservation_id}:"
            f"{policy.access_key}:r{source.revision}"
        )

    @staticmethod
    def _revoke_request(
        access: ReservationAccess,
        materialized: ProvisionedAccess,
    ) -> RevokeAccessRequest:
        return RevokeAccessRequest(
            organization_id=access.organization_id,
            reservation_id=access.reservation_id,
            reservation_revision=access.reservation_revision,
            access_key=access.access_key,
            kind=access.kind,
            materialization_key=access.materialization_key,
            access_uri=materialized.access_uri,
            external_ref=materialized.external_ref,
            public_data=materialized.public_data,
        )

    @staticmethod
    def _validate_claim_tenant(
        organization_id: UUID,
        work_claim: DeliveryWorkClaim,
    ) -> None:
        if organization_id != work_claim.organization_id:
            raise ValueError("delivery work claim tenant mismatch")
