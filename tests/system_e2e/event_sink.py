from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

EVENT_FILE = Path(os.environ.get("E2E_EVENT_FILE", "/sink/events.jsonl"))


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
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
        EVENT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with EVENT_FILE.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, sort_keys=True) + "\n")
        body = b'{"accepted":true}'
        self.send_response(202)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/health":
            body = b'{"status":"ok"}'
        elif self.path == "/events":
            events: list[object] = []
            if EVENT_FILE.exists():
                for line in EVENT_FILE.read_text(encoding="utf-8").splitlines():
                    events.append(json.loads(line))
            body = json.dumps({"events": events}).encode("utf-8")
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", 8090), Handler)
    server.serve_forever()
