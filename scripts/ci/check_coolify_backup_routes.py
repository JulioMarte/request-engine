from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_PARAMETER = re.compile(r"\{[^}]+\}")


def main() -> int:
    rows = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    normalized: set[tuple[str, str]] = set()
    for row in rows:
        uri = _PARAMETER.sub("{}", str(row.get("uri", ""))).lstrip("/")
        raw_methods = row.get("method", "")
        if isinstance(raw_methods, list):
            methods = [str(value) for value in raw_methods]
        else:
            methods = str(raw_methods).split("|")
        normalized.update((method.upper(), uri) for method in methods if method)

    required = {
        ("GET", "api/v1/databases/{}/backups"),
        ("POST", "api/v1/databases/{}/backups"),
        ("PATCH", "api/v1/databases/{}/backups/{}"),
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
