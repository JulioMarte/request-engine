from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import cast

EVENT_FILE = Path(os.environ.get("E2E_EVENT_FILE", "/sink/events.jsonl"))
ATTEMPT_FILE = Path(os.environ.get("E2E_EVENT_ATTEMPT_FILE", "/sink/attempts.jsonl"))
_STATE_LOCK = threading.Lock()
_blocked_state = False


def _append_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, sort_keys=True) + "\n")


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    values: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        decoded: object = json.loads(line)
        if isinstance(decoded, dict):
            values.append(cast(dict[str, object], decoded))
    return values


def _blocked() -> bool:
    with _STATE_LOCK:
        return _blocked_state


def _set_blocked(value: bool) -> None:
    global _blocked_state
    with _STATE_LOCK:
        _blocked_state = value


class Handler(BaseHTTPRequestHandler):
    def _json_response(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if self.path == "/control/block":
            _set_blocked(True)
            self._json_response(200, {"blocked": True})
            return
        if self.path == "/control/release":
            _set_blocked(False)
            self._json_response(200, {"blocked": False})
            return
        if self.path != "/events":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload: object = json.loads(self.rfile.read(length))
        except (ValueError, json.JSONDecodeError):
            self.send_error(400)
            return
        if not isinstance(payload, dict):
            self.send_error(422)
            return
        event = cast(dict[str, object], payload)
        blocked = _blocked()
        _append_json(ATTEMPT_FILE, {"blocked": blocked, "event": event})
        if blocked:
            self._json_response(503, {"accepted": False, "blocked": True})
            return
        _append_json(EVENT_FILE, event)
        self._json_response(202, {"accepted": True, "blocked": False})

    def do_GET(self) -> None:
        if self.path == "/health":
            self._json_response(200, {"status": "ok"})
            return
        if self.path == "/status":
            attempts = _read_jsonl(ATTEMPT_FILE)
            events = _read_jsonl(EVENT_FILE)
            self._json_response(
                200,
                {
                    "blocked": _blocked(),
                    "attempt_count": len(attempts),
                    "accepted_count": len(events),
                },
            )
            return
        if self.path == "/events":
            self._json_response(200, {"events": _read_jsonl(EVENT_FILE)})
            return
        if self.path == "/attempts":
            self._json_response(200, {"attempts": _read_jsonl(ATTEMPT_FILE)})
            return
        self.send_error(404)

    def log_message(self, format: str, *args: object) -> None:
        return


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", 8090), Handler)
    server.serve_forever()
