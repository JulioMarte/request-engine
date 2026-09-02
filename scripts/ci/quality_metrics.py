from __future__ import annotations

import ast
import io
import math
import subprocess
import tarfile
import tokenize
from pathlib import Path
from typing import Any

CONFIG_SUFFIXES = {".cfg", ".ini", ".json", ".toml", ".yaml", ".yml"}
GENERATED_PATH_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "generated",
    "node_modules",
}
IGNORED_TOKEN_TYPES = {
    tokenize.COMMENT,
    tokenize.NL,
    tokenize.NEWLINE,
    tokenize.ENCODING,
    tokenize.ENDMARKER,
    tokenize.INDENT,
    tokenize.DEDENT,
}
BUSINESS_MODULE_ROOT = ("src", "request_engine", "modules")


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        check=check,
        text=True,
        capture_output=True,
    )


def repository_sha(ref: str = "HEAD") -> str:
    return git("rev-parse", ref).stdout.strip()


def tracked_files() -> list[Path]:
    result = git("ls-files", "-z")
    return [Path(item) for item in result.stdout.split("\0") if item]


def effective_code_lines(source: str) -> int:
    lines: set[int] = set()
    tokens = tokenize.generate_tokens(io.StringIO(source).readline)
    for token in tokens:
        if token.type in IGNORED_TOKEN_TYPES:
            continue
        lines.update(range(token.start[0], token.end[0] + 1))
    return len(lines)


def nonblank_text_lines(source: str) -> int:
    return sum(1 for line in source.splitlines() if line.strip())


def generated_reason(path: Path, source: str | None = None) -> str | None:
    """Return an authoritative generated-code reason.

    Source comments are deliberately not authority. A coding agent can write an
    ``@generated`` comment, so generated exclusion is limited to controlled path
    or filename conventions. ``source`` remains in the signature for callers that
    already provide it and for future provenance checks.
    """
    _ = source
    lowered_parts = {part.lower() for part in path.parts}
    matched = lowered_parts & GENERATED_PATH_PARTS
    if matched:
        return f"generated-path:{sorted(matched)[0]}"
    lowered_name = path.name.lower()
    if lowered_name.endswith(("_generated.py", ".generated.py")):
        return "generated-filename"
    return None


def classify_path(path: Path) -> str | None:
    parts = path.parts
    if not parts:
        return None
    if parts[0] == "tests":
        return "tests"
    if parts[0] == "scripts":
        return "scripts"
    if parts[0] == "migrations":
        return "migrations"
    if parts[0] == "src" and path.suffix == ".py":
        if len(parts) >= 6 and parts[1:3] == ("request_engine", "modules"):
            layer = parts[4]
            if layer in {"adapters", "api", "application", "contracts", "domain"}:
                return f"production_{layer}"
        if "bootstrap" in parts or (len(parts) >= 3 and parts[2] == "entrypoints"):
            return "production_composition"
        return "production_other"
    if path.suffix.lower() in CONFIG_SUFFIXES:
        return "config"
    if path.suffix == ".py":
        return "python_other"
    return None


def business_module_for_path(path: Path) -> str | None:
    parts = path.parts
    if len(parts) >= 4 and parts[:3] == BUSINESS_MODULE_ROOT:
        return parts[3]
    return None


def _resolved_import_from(path: Path, node: ast.ImportFrom) -> str | None:
    if node.level == 0:
        return node.module
    parts = list(path.parts)
    if not parts or parts[0] != "src":
        return None
    package = parts[1:-1]
    climb = node.level - 1
    if climb > len(package):
        return None
    resolved = package[: len(package) - climb]
    if node.module:
        resolved.extend(node.module.split("."))
    return ".".join(resolved)


def _business_targets_from_import(path: Path, node: ast.Import | ast.ImportFrom) -> set[str]:
    targets: set[str] = set()
    if isinstance(node, ast.Import):
        names = [alias.name for alias in node.names]
    else:
        resolved = _resolved_import_from(path, node)
        names = [resolved] if resolved else []
        if resolved == "request_engine.modules":
            names.extend(f"{resolved}.{alias.name}" for alias in node.names)
    for name in names:
        if not name:
            continue
        parts = name.split(".")
        if len(parts) >= 3 and parts[:2] == ["request_engine", "modules"]:
            targets.add(parts[2])
    return targets


def module_import_edges_from_source(path: Path, source: str) -> set[tuple[str, str]]:
    source_module = business_module_for_path(path)
    if source_module is None:
        return set()
    tree = ast.parse(source, filename=path.as_posix())
    edges: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Import | ast.ImportFrom):
            continue
        for target in _business_targets_from_import(path, node):
            if target != source_module:
                edges.add((source_module, target))
    return edges


def _current_business_module_sources() -> list[tuple[Path, str]]:
    sources: list[tuple[Path, str]] = []
    for path in tracked_files():
        if business_module_for_path(path) is None or path.suffix != ".py" or not path.is_file():
            continue
        source = path.read_text(encoding="utf-8")
        if generated_reason(path, source) is None:
            sources.append((path, source))
    return sources


def _business_module_sources_at_ref(ref: str) -> list[tuple[Path, str]]:
    result = subprocess.run(
        ["git", "archive", "--format=tar", ref, "/".join(BUSINESS_MODULE_ROOT)],
        check=True,
        capture_output=True,
    )
    sources: list[tuple[Path, str]] = []
    with tarfile.open(fileobj=io.BytesIO(result.stdout), mode="r:") as archive:
        for member in archive.getmembers():
            if not member.isfile() or not member.name.endswith(".py"):
                continue
            extracted = archive.extractfile(member)
            if extracted is None:
                continue
            path = Path(member.name)
            source = extracted.read().decode("utf-8")
            if generated_reason(path, source) is None:
                sources.append((path, source))
    return sources


def business_module_dependency_snapshot(ref: str | None = None) -> dict[str, object]:
    sources = (
        _current_business_module_sources()
        if ref is None
        else _business_module_sources_at_ref(ref)
    )
    modules = {
        module
        for path, _ in sources
        if (module := business_module_for_path(path)) is not None
    }
    edges: set[tuple[str, str]] = set()
    for path, source in sources:
        edges.update(module_import_edges_from_source(path, source))
    for source, target in edges:
        modules.add(source)
        modules.add(target)

    module_records: list[dict[str, object]] = []
    for module in sorted(modules):
        outbound = sorted(target for source, target in edges if source == module)
        inbound = sorted(source for source, target in edges if target == module)
        module_records.append(
            {
                "module": module,
                "fan_in": len(inbound),
                "fan_out": len(outbound),
                "inbound_modules": inbound,
                "outbound_modules": outbound,
            }
        )
    return {
        "modules": module_records,
        "edges": [
            {"source": source, "target": target}
            for source, target in sorted(edges)
        ],
    }


def function_records(path: Path, source: str) -> list[dict[str, object]]:
    tree = ast.parse(source, filename=path.as_posix())
    records: list[dict[str, object]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        end = node.end_lineno or node.lineno
        records.append(
            {
                "path": path.as_posix(),
                "subject": node.name,
                "line": node.lineno,
                "function_loc": end - node.lineno + 1,
            }
        )
    return records


def _is_docstring(node: ast.stmt) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


def _function_is_one_call_forwarder(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    body = list(node.body)
    if body and _is_docstring(body[0]):
        body = body[1:]
    if len(body) != 1:
        return False
    statement = body[0]
    if isinstance(statement, ast.Return):
        return isinstance(statement.value, ast.Call)
    if isinstance(statement, ast.Expr):
        return isinstance(statement.value, ast.Call)
    return False


def navigation_observation(path: Path, source: str) -> dict[str, object]:
    tree = ast.parse(source, filename=path.as_posix())
    body = [node for node in tree.body if not _is_docstring(node)]
    functions = [node for node in body if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)]
    forwarding = [node for node in functions if _function_is_one_call_forwarder(node)]
    reexport_allowed = (ast.Import, ast.ImportFrom, ast.Assign, ast.AnnAssign)
    reexport_only = bool(body) and all(isinstance(node, reexport_allowed) for node in body)
    forwarding_only = bool(functions) and len(functions) == len(forwarding)
    return {
        "path": path.as_posix(),
        "function_count": len(functions),
        "one_call_forwarder_count": len(forwarding),
        "forwarding_only_functions": forwarding_only,
        "reexport_only_module": reexport_only,
        "interpretation": "none",
    }


def nearest_rank_percentile(values: list[int], percentile: int) -> int | None:
    if not values:
        return None
    if not 0 <= percentile <= 100:
        raise ValueError("percentile must be between 0 and 100")
    ordered = sorted(values)
    rank = max(1, math.ceil((percentile / 100) * len(ordered)))
    return ordered[rank - 1]


def distribution(values: list[int]) -> dict[str, int | None]:
    if not values:
        return {
            "count": 0,
            "min": None,
            "p50": None,
            "p75": None,
            "p90": None,
            "p95": None,
            "p99": None,
            "max": None,
        }
    return {
        "count": len(values),
        "min": min(values),
        "p50": nearest_rank_percentile(values, 50),
        "p75": nearest_rank_percentile(values, 75),
        "p90": nearest_rank_percentile(values, 90),
        "p95": nearest_rank_percentile(values, 95),
        "p99": nearest_rank_percentile(values, 99),
        "max": max(values),
    }


def parse_ruff_complexity_payload(payload: Any) -> list[dict[str, object]]:
    if not isinstance(payload, list):
        raise ValueError("Ruff C901 payload must be a list")
    records: list[dict[str, object]] = []
    for item in payload:
        if not isinstance(item, dict) or item.get("code") != "C901":
            continue
        message = str(item.get("message", ""))
        left = message.rfind("(")
        middle = message.rfind(" > ")
        right = message.rfind(")")
        if left == -1 or middle == -1 or right == -1 or not left < middle < right:
            continue
        try:
            score = int(message[left + 1 : middle])
        except ValueError:
            continue
        subject = "<function>"
        if message.startswith("`") and "`" in message[1:]:
            subject = message[1 : message.index("`", 1)]
        location = item.get("location") if isinstance(item.get("location"), dict) else {}
        records.append(
            {
                "path": str(item.get("filename", "<unknown>")),
                "subject": subject,
                "line": location.get("row"),
                "mccabe": score,
            }
        )
    return records
