import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src" / "request_engine"
HTTP_ENTRYPOINT = SRC_ROOT / "entrypoints" / "http"
MODULES_ROOT = SRC_ROOT / "modules"

HTTP_MODULES = {"requests", "catalog", "booking", "queue"}
ENTRYPOINT_ALLOWED_PYTHON = {"__init__.py", "app.py", "errors.py", "security.py"}


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return imports


def test_http_business_transport_is_owned_by_modules() -> None:
    actual_python = {path.name for path in HTTP_ENTRYPOINT.glob("*.py")}
    assert actual_python <= ENTRYPOINT_ALLOWED_PYTHON

    for module_name in HTTP_MODULES:
        api_root = MODULES_ROOT / module_name / "api"
        assert (api_root / "__init__.py").is_file()
        assert (api_root / "router.py").is_file()
        assert (api_root / "models.py").is_file()


def test_http_entrypoint_composes_module_api_surfaces_only() -> None:
    violations: list[str] = []
    for path in HTTP_ENTRYPOINT.glob("*.py"):
        for import_name in _imports(path):
            prefix = "request_engine.modules."
            if not import_name.startswith(prefix):
                continue
            parts = import_name.split(".")
            if len(parts) < 4 or parts[3] != "api":
                violations.append(f"{path.relative_to(REPO_ROOT)} -> {import_name}")
    assert violations == []


def test_entrypoints_do_not_reach_into_module_adapters() -> None:
    violations: list[str] = []
    entrypoints_root = SRC_ROOT / "entrypoints"
    for path in entrypoints_root.rglob("*.py"):
        for import_name in _imports(path):
            if import_name.startswith("request_engine.modules.") and ".adapters." in import_name:
                violations.append(f"{path.relative_to(REPO_ROOT)} -> {import_name}")
    assert violations == []


def test_http_authentication_surface_is_explicit_platform_contract() -> None:
    surface = SRC_ROOT / "platform" / "security" / "http.py"
    assert surface.is_file()
    source = surface.read_text(encoding="utf-8")
    assert "class ActorResolver(Protocol)" in source
    assert "class AuthenticationRequired(Exception)" in source


def test_http_module_installers_are_connection_surfaces() -> None:
    for module_name in HTTP_MODULES:
        source = (MODULES_ROOT / module_name / "api" / "__init__.py").read_text(
            encoding="utf-8"
        )
        assert "def install_http(" in source
        assert "session_factory: SessionFactory" in source
        assert "actor_resolver: ActorResolver" in source
