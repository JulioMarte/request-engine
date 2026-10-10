"""Local webhook fixture that records Alertmanager status values."""

from __future__ import annotations

import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--port", type=int, required=True)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--mode-file", type=Path)
parser.add_argument("--bind", default="127.0.0.1")
args = parser.parse_args()
last_watchdog_timestamp: float | None = None


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/watchdog":
            body = json.dumps({"last_accepted_timestamp": last_watchdog_timestamp}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path != "/healthz":
            self.send_error(404)
            return
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ready")

    def do_PUT(self) -> None:  # noqa: N802
        if self.path not in {"/control/fail", "/control/accept"} or args.mode_file is None:
            self.send_error(404)
            return
        mode = "fail" if self.path.endswith("/fail") else "accept"
        args.mode_file.parent.mkdir(parents=True, exist_ok=True)
        args.mode_file.write_text(mode, encoding="utf-8")
        self.send_response(200)
        self.end_headers()
        self.wfile.write(mode.encode("ascii"))

    def do_POST(self) -> None:  # noqa: N802
        global last_watchdog_timestamp
        if self.path != "/alerts":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length))
        alertnames = ",".join(
            sorted(
                str(alert.get("labels", {}).get("alertname", ""))
                for alert in payload.get("alerts", [])
            )
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        mode = args.mode_file.read_text(encoding="utf-8").strip() if args.mode_file else "accept"
        if mode == "fail":
            with args.output.open("a", encoding="utf-8") as stream:
                stream.write(f"rejected|{alertnames}\n")
            self.send_response(503)
            self.end_headers()
            self.wfile.write(b"temporary receiver failure")
            return
        if any(
            alert.get("labels", {}).get("alertname") == "Watchdog"
            and alert.get("status", payload.get("status")) == "firing"
            for alert in payload.get("alerts", [])
        ):
            last_watchdog_timestamp = time.time()
        with args.output.open("a", encoding="utf-8") as stream:
            stream.write(f"{payload.get('status', 'unknown')}|{alertnames}\n")
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"accepted")

    def log_message(self, format: str, *args: object) -> None:
        return


HTTPServer((args.bind, args.port), Handler).serve_forever()
