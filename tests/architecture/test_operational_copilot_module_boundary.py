import ast
from pathlib import Path

MODULE_ROOT = Path("src/request_engine/modules/operational_copilot")
OWN_PACKAGE_PREFIX = "request_engine.modules.operational_copilot"
API_PACKAGE_PREFIX = "src/request_engine/modules/operational_copilot/api"


def _collect_imports(tree: ast.Module) -> list[str]:
    imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    imports.extend(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    return imports


def _relative_imports(tree: ast.Module) -> list[str]:
    return [
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.level > 0
    ]


def test_copilot_consumes_owner_modules_only_through_contracts() -> None:
    violations: list[str] = []
    for path in MODULE_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for imported in _collect_imports(tree):
            if not imported.startswith("request_engine.modules."):
                continue
            parts = imported.split(".")
            if len(parts) < 4 or parts[2] == "operational_copilot":
                continue
            if parts[3] != "contracts":
                violations.append(f"{path.as_posix()}: {imported}")
    assert not violations


def test_copilot_has_no_relative_import_escape_hatches() -> None:
    violations: list[str] = []
    for path in MODULE_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for imported in _relative_imports(tree):
            violations.append(f"{path.as_posix()}: relative import of {imported}")
    assert not violations


def test_only_api_layer_uses_http_framework() -> None:
    violations: list[str] = []
    for path in MODULE_ROOT.rglob("*.py"):
        if path.as_posix().startswith(API_PACKAGE_PREFIX):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for imported in _collect_imports(tree):
            if imported == "fastapi" or imported.startswith("fastapi."):
                violations.append(f"{path.as_posix()}: {imported}")
    assert not violations
