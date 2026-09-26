from __future__ import annotations

import re
import sys
from pathlib import Path

_ROUTE = re.compile(
    r"Route::(?P<method>get|post|patch)\s*\(\s*['\"](?P<uri>[^'\"]+)",
    re.IGNORECASE,
)
_PARAMETER = re.compile(r"\{[^}]+\}")


def main() -> int:
    source = Path(sys.argv[1]).read_text(encoding="utf-8")
    normalized = {
        (match.group("method").upper(), _PARAMETER.sub("{}", match.group("uri")).lstrip("/"))
        for match in _ROUTE.finditer(source)
    }
    required = {
        ("GET", "databases/{}/backups"),
        ("POST", "databases/{}/backups"),
        ("PATCH", "databases/{}/backups/{}"),
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
