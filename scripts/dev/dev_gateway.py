"""DEVELOPMENT-ONLY loopback receiver for the local stack worker.

It accepts what a deployment normally points at real infrastructure:

- ``POST http://dev-gateway:8090/events``: the reference HTTP outbox publisher;
- ``POST https://dev-gateway:8443/webhook``: the HTTPS webhook delivery handoff;
- ``GET  https://dev-gateway:8443/webhook/status/<dedupe_key>``: delivery lookup.

Everything is kept in memory and can be inspected on the HTTP port through
``GET /status``, ``/events`` and ``/deliveries``. Nothing is ever delivered to a
person. It refuses to start unless explicitly acknowledged as development-only,
and it is only referenced by ``compose.dev.yaml``; production keeps failing
closed without a configured publisher and an operator-supplied webhook.
"""

from __future__ import annotations

import json
import os
import ssl
import threading
import uuid
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import cast

_ACK_ENV = "RE_DEV_GATEWAY_DEVELOPMENT_ONLY"
_LIMIT = 500
_lock = threading.Lock()
_events: deque[dict[str, object]] = deque(maxlen=_LIMIT)
_deliveries: dict[str, dict[str, object]] = {}


def _record_delivery(handoff: dict[str, object]) -> str:
    key = str(handoff.get("dedupe_key") or uuid.uuid4())
    with _lock:
        known = _deliveries.get(key)
        if known is not None:
            return str(known["provider_message_id"])
        message_id = f"dev-gateway-{uuid.uuid4()}"
        if len(_deliveries) >= _LIMIT:
            _deliveries.pop(next(iter(_deliveries)))
        _deliveries[key] = {"provider_message_id": message_id, "handoff": handoff}
        return message_id


class _Handler(BaseHTTPRequestHandler):
    secure = False

    def _json(self, status: int, payload: object) -> None:
        body = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict[str, object] | None:
        try:
            decoded: object = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        except (TypeError, ValueError):
            return None
        return cast(dict[str, object], decoded) if isinstance(decoded, dict) else None

    def do_POST(self) -> None:
        payload = self._body()
        if payload is None:
            self._json(400, {"error": "expected a JSON object"})
        elif not self.secure and self.path == "/events":
            with _lock:
                _events.append(payload)
            self._json(202, {"accepted": True})
        elif self.secure and self.path == "/webhook":
            self._json(202, {"provider_message_id": _record_delivery(payload)})
        else:
            self._json(404, {"error": "unknown dev gateway route"})

    def do_GET(self) -> None:
        prefix = "/webhook/status/"
        if self.secure and self.path.startswith(prefix):
            with _lock:
                known = _deliveries.get(self.path[len(prefix) :])
            if known is None:
                self._json(404, {"status": "unknown"})
            else:
                self._json(200, {"status": "delivered", **known})
            return
        with _lock:
            views: dict[str, object] = {
                "/health": {"status": "ok", "development_only": True},
                "/status": {"events": len(_events), "deliveries": len(_deliveries)},
                "/events": {"events": list(_events)},
                "/deliveries": {"deliveries": list(_deliveries.values())},
            }
        view = None if self.secure else views.get(self.path)
        if view is None:
            self._json(404, {"error": "unknown dev gateway route"})
        else:
            self._json(200, view)

    def log_message(self, format: str, *args: object) -> None:
        print(f"dev-gateway {'https' if self.secure else 'http'}: {format % args}", flush=True)


class _SecureHandler(_Handler):
    secure = True


def main() -> None:
    if os.environ.get(_ACK_ENV) != "acknowledged":
        raise SystemExit(f"{_ACK_ENV}=acknowledged is required: this receiver is dev-only")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(
        os.environ["RE_DEV_GATEWAY_CERT_FILE"], os.environ["RE_DEV_GATEWAY_KEY_FILE"]
    )
    secure = ThreadingHTTPServer(("0.0.0.0", 8443), _SecureHandler)
    secure.socket = context.wrap_socket(secure.socket, server_side=True)
    threading.Thread(target=secure.serve_forever, daemon=True).start()
    print("dev-gateway: DEVELOPMENT ONLY; outbox http :8090, webhook https :8443", flush=True)
    ThreadingHTTPServer(("0.0.0.0", 8090), _Handler).serve_forever()


if __name__ == "__main__":
    main()
