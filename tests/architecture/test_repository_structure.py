import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src" / "request_engine"
MODULES_ROOT = SRC_ROOT / "modules"

BASELINE_MODULES = {
    "tenancy",
    "catalog",
    "requests",
    "booking",
    "queue",
    "communications",
}

DEFERRED_MODULES = {
    "delivery",
    "payments",
    "dispatch",
}

BUSINESS_MODULES = frozenset(
    path.name for path in MODULES_ROOT.iterdir() if path.is_dir() and not path.name.startswith("__")
)

V3_CANONICAL_DOCS = {
    "docs/11-capability-first-v3.md",
    "docs/v3/01-capability-contracts.md",
    "docs/v3/02-pre-sql-contract.md",
    "docs/v3/sql-disposition.md",
}

FORBIDDEN_HORIZONTAL_ROOTS = {
    "api",
    "application",
    "domain",
    "infrastructure",
    "workers",
}

FORBIDDEN_GENERIC_PLATFORM_BUCKETS = {"common", "shared", "utils", "helpers"}

DOMAIN_FORBIDDEN_IMPORT_PREFIXES = (
    "fastapi",
    "sqlalchemy",
    "request_engine.bootstrap",
)
APPLICATION_FORBIDDEN_IMPORT_PREFIXES = ("fastapi",)


def _python_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return [path for path in root.rglob("*.py") if "__pycache__" not in path.parts]


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    return imported


def _is_prefixed(import_name: str, prefix: str) -> bool:
    return import_name == prefix or import_name.startswith(f"{prefix}.")


def test_business_modules_have_explicit_ownership_docs() -> None:
    assert BASELINE_MODULES <= BUSINESS_MODULES
    assert DEFERRED_MODULES <= BUSINESS_MODULES
    for module_name in BUSINESS_MODULES:
        assert (MODULES_ROOT / module_name / "README.md").is_file()


def test_baseline_and_deferred_module_labels_are_consistent() -> None:
    assert BASELINE_MODULES.isdisjoint(DEFERRED_MODULES)


def test_v3_canonical_contracts_exist() -> None:
    missing = {path for path in V3_CANONICAL_DOCS if not (REPO_ROOT / path).is_file()}
    assert missing == set()


def test_horizontal_business_layer_roots_do_not_reappear() -> None:
    unexpected = {name for name in FORBIDDEN_HORIZONTAL_ROOTS if (SRC_ROOT / name).exists()}
    assert unexpected == set()


def test_platform_does_not_gain_generic_dumping_ground_packages() -> None:
    platform_root = SRC_ROOT / "platform"
    unexpected = {
        name for name in FORBIDDEN_GENERIC_PLATFORM_BUCKETS if (platform_root / name).exists()
    }
    assert unexpected == set()


def test_durable_scheduling_has_an_explicit_platform_boundary() -> None:
    scheduling_root = SRC_ROOT / "platform" / "scheduling"
    assert (scheduling_root / "__init__.py").is_file()
    assert (scheduling_root / "README.md").is_file()


def test_runtime_settings_are_owned_by_bootstrap() -> None:
    assert not (SRC_ROOT / "config.py").exists()
    assert (SRC_ROOT / "bootstrap" / "settings.py").is_file()


def test_executable_sql_is_owned_by_migrations_not_docs() -> None:
    sql_in_docs = list((REPO_ROOT / "docs").glob("**/*.sql"))
    assert sql_in_docs == []

    design_root = REPO_ROOT / "migrations" / "sql" / "design_chain"
    assert design_root.is_dir()
    assert list(design_root.glob("*.sql"))


def test_test_suites_have_explicit_integration_boundary() -> None:
    assert (REPO_ROOT / "tests" / "integration").is_dir()


def test_agent_guidance_exists_at_important_boundaries() -> None:
    required = [
        REPO_ROOT / "AGENTS.md",
        REPO_ROOT / "docs" / "AGENTS.md",
        REPO_ROOT / "migrations" / "AGENTS.md",
        MODULES_ROOT / "AGENTS.md",
        REPO_ROOT / "tests" / "AGENTS.md",
    ]
    assert all(path.is_file() for path in required)


def test_domain_code_does_not_import_framework_or_bootstrap_layers() -> None:
    violations: list[str] = []
    for module_name in BUSINESS_MODULES:
        for path in _python_files(MODULES_ROOT / module_name / "domain"):
            for import_name in _imports(path):
                if any(
                    _is_prefixed(import_name, prefix) for prefix in DOMAIN_FORBIDDEN_IMPORT_PREFIXES
                ):
                    violations.append(f"{path.relative_to(REPO_ROOT)} -> {import_name}")

    assert violations == []


def test_application_code_does_not_import_transport_frameworks() -> None:
    violations: list[str] = []
    for module_name in BUSINESS_MODULES:
        for path in _python_files(MODULES_ROOT / module_name / "application"):
            for import_name in _imports(path):
                if any(
                    _is_prefixed(import_name, prefix)
                    for prefix in APPLICATION_FORBIDDEN_IMPORT_PREFIXES
                ):
                    violations.append(f"{path.relative_to(REPO_ROOT)} -> {import_name}")

    assert violations == []


def test_platform_does_not_import_business_modules() -> None:
    violations: list[str] = []
    for path in _python_files(SRC_ROOT / "platform"):
        for import_name in _imports(path):
            if _is_prefixed(import_name, "request_engine.modules"):
                violations.append(f"{path.relative_to(REPO_ROOT)} -> {import_name}")

    assert violations == []


def test_cross_module_imports_use_contracts_only() -> None:
    violations: list[str] = []

    for owner in BUSINESS_MODULES:
        owner_root = MODULES_ROOT / owner
        for path in _python_files(owner_root):
            for import_name in _imports(path):
                prefix = "request_engine.modules."
                if not import_name.startswith(prefix):
                    continue

                parts = import_name.split(".")
                if len(parts) < 3:
                    continue

                target = parts[2]
                if target == owner or target not in BUSINESS_MODULES:
                    continue

                allowed_prefix = f"request_engine.modules.{target}.contracts"
                if not _is_prefixed(import_name, allowed_prefix):
                    violations.append(f"{path.relative_to(REPO_ROOT)} -> {import_name}")

    assert violations == []


def test_baseline_modules_do_not_depend_on_deferred_modules() -> None:
    violations: list[str] = []

    for owner in BASELINE_MODULES:
        for path in _python_files(MODULES_ROOT / owner):
            for import_name in _imports(path):
                for deferred in DEFERRED_MODULES:
                    deferred_prefix = f"request_engine.modules.{deferred}"
                    if _is_prefixed(import_name, deferred_prefix):
                        violations.append(f"{path.relative_to(REPO_ROOT)} -> {import_name}")

    assert violations == []
