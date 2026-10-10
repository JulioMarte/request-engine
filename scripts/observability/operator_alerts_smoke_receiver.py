"""Local webhook fixture that records Alertmanager status values."""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--port", type=int, required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length))
        alertnames = ",".join(
            sorted(
                str(alert.get("labels", {}).get("alertname", ""))
                for alert in payload.get("alerts", [])
            )
        )
        with args.output.open("a", encoding="utf-8") as stream:
            stream.write(f"{payload.get('status', 'unknown')}|{alertnames}\n")
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"accepted")

    def log_message(self, _format: str, *_args: object) -> None:
        return


HTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
