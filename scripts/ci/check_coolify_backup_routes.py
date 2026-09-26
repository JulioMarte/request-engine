from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    rows = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    routes = {(tuple(row.get("method", [])), row.get("uri", "")) for row in rows}
    required = {
        ("GET", "api/v1/databases/{uuid}/backups"),
        ("POST", "api/v1/databases/{uuid}/backups"),
        ("PATCH", "api/v1/databases/{uuid}/backups/{scheduled_backup_uuid}"),
    }
    normalized = {
        (method, uri)
        for methods, uri in routes
        for method in (methods if isinstance(methods, tuple) else (methods,))
    }
    missing = sorted(required - normalized)
    if missing:
        print("Coolify image is missing routes required by Request Engine:", file=sys.stderr)
        for method, uri in missing:
            print(f"  {method} {uri}", file=sys.stderr)
        return 1
    print("Coolify scheduled-backup API contract routes are present.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
