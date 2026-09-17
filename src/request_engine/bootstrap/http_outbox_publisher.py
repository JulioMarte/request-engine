"""Reference HTTP outbox publisher for deployable worker topologies.

The publisher deliberately speaks ordinary HTTP and has no E2E-specific imports. A
reference deployment can point it at any endpoint that accepts the canonical outbox
event envelope. Test deployments use an isolated observable sink; production users may
replace the factory through REQUEST_ENGINE_OUTBOX_PUBLISHER_FACTORY.
"""

from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.request
from dataclasses import asdict

from request_engine.entrypoints.worker.outbox_runtime import OutboxEvent, OutboxPublisher

OUTBOX_PUBLISH_URL_ENV = "REQUEST_ENGINE_OUTBOX_PUBLISH_URL"


class HttpOutboxPublisher(OutboxPublisher):
    def __init__(self, endpoint: str) -> None:
        endpoint = endpoint.strip()
        if not endpoint.startswith(("http://", "https://")):
            raise ValueError("outbox publish endpoint must be an absolute HTTP(S) URL")
        self._endpoint = endpoint

    async def publish(self, event: OutboxEvent) -> None:
        await asyncio.to_thread(self._publish_sync, event)

    def _publish_sync(self, event: OutboxEvent) -> None:
        payload = asdict(event)
        body = json.dumps(payload, default=str, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(
            self._endpoint,
            data=body,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                if response.status < 200 or response.status >= 300:
                    raise RuntimeError(f"outbox publisher received HTTP {response.status}")
        except urllib.error.URLError as exc:
            raise RuntimeError("outbox publisher delivery failed") from exc


def create_publisher() -> OutboxPublisher:
    endpoint = os.environ.get(OUTBOX_PUBLISH_URL_ENV, "")
    if not endpoint:
        raise RuntimeError(f"{OUTBOX_PUBLISH_URL_ENV} is required and must not be empty")
    return HttpOutboxPublisher(endpoint)
