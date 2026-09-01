"""Provider doubles standing only at the external transport boundary.

The authoritative business/database path of the delivery suites stays real;
these fakes script only the external provider transport edge.
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

from request_engine.modules.communications.contracts.delivery import (
    CommunicationDeliveryProvider,
    ProviderDeliveryResult,
    ProviderDeliveryStatus,
    ProviderLookupRequest,
    ProviderSendRequest,
)


class ScriptedProvider(CommunicationDeliveryProvider):
    def __init__(
        self,
        *,
        send: ProviderDeliveryResult | Exception | None = None,
        lookup: ProviderDeliveryResult | Exception | None = None,
    ) -> None:
        self.send_result = send
        self.lookup_result = lookup
        self.send_calls: list[ProviderSendRequest] = []
        self.lookup_calls: list[ProviderLookupRequest] = []

    async def send(self, request: ProviderSendRequest) -> ProviderDeliveryResult:
        self.send_calls.append(request)
        if isinstance(self.send_result, Exception):
            raise self.send_result
        if self.send_result is None:
            raise AssertionError("unexpected provider.send call")
        return self.send_result

    async def lookup(self, request: ProviderLookupRequest) -> ProviderDeliveryResult:
        self.lookup_calls.append(request)
        if isinstance(self.lookup_result, Exception):
            raise self.lookup_result
        if self.lookup_result is None:
            raise AssertionError("unexpected provider.lookup call")
        return self.lookup_result


class UniqueDeliveredProvider(CommunicationDeliveryProvider):
    def __init__(self) -> None:
        self.send_calls: list[ProviderSendRequest] = []
        self.lookup_calls: list[ProviderLookupRequest] = []

    async def send(self, request: ProviderSendRequest) -> ProviderDeliveryResult:
        self.send_calls.append(request)
        return ProviderDeliveryResult(
            status=ProviderDeliveryStatus.DELIVERED,
            provider_message_id=f"msg-{request.delivery_id}",
        )

    async def lookup(self, request: ProviderLookupRequest) -> ProviderDeliveryResult:
        self.lookup_calls.append(request)
        raise AssertionError("contention scenario must not reconcile")


class DeliveredProvider(CommunicationDeliveryProvider):
    def __init__(self) -> None:
        self.send_calls: list[ProviderSendRequest] = []

    async def send(self, request: ProviderSendRequest) -> ProviderDeliveryResult:
        self.send_calls.append(request)
        return ProviderDeliveryResult(
            status=ProviderDeliveryStatus.DELIVERED,
            provider_message_id=f"msg-{request.delivery_id}",
        )

    async def lookup(self, request: ProviderLookupRequest) -> ProviderDeliveryResult:
        raise AssertionError(f"unexpected provider lookup for {request.delivery_id}")


class OrderedConflictingLookupProvider(CommunicationDeliveryProvider):
    def __init__(self) -> None:
        self.lookup_calls: list[ProviderLookupRequest] = []
        self.first_started = asyncio.Event()
        self.second_started = asyncio.Event()
        self.release_failure = asyncio.Event()
        self.release_delivered = asyncio.Event()

    async def send(self, request: ProviderSendRequest) -> ProviderDeliveryResult:
        del request
        raise AssertionError("reconciliation race must never call provider.send")

    async def lookup(self, request: ProviderLookupRequest) -> ProviderDeliveryResult:
        self.lookup_calls.append(request)
        call_no = len(self.lookup_calls)
        if call_no == 1:
            self.first_started.set()
            await self.release_failure.wait()
            return ProviderDeliveryResult(
                status=ProviderDeliveryStatus.FAILED,
                retryable=False,
                result_data={"error_class": "provider_terminal_failure"},
            )
        if call_no == 2:
            self.second_started.set()
            await self.release_delivered.wait()
            return ProviderDeliveryResult(
                status=ProviderDeliveryStatus.DELIVERED,
                provider_message_id=f"late-delivered-{uuid4().hex}",
            )
        raise AssertionError("unexpected third provider.lookup call")
