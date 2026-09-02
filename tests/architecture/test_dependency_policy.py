import ast
from collections.abc import Iterable
from pathlib import Path

from dependency_policy import FRAMEWORK_OR_INFRA_PREFIXES, MODULE_DEPENDENCY_POLICY

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
MODULES_ROOT = SRC_ROOT / "request_engine" / "modules"
ALL_MODULES = frozenset(
    path.name for path in MODULES_ROOT.iterdir() if path.is_dir() and not path.name.startswith("__")
)


def _python_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return [path for path in root.rglob("*.py") if "__pycache__" not in path.parts]


def _resolved_import_from(path: Path, node: ast.ImportFrom) -> str | None:
    if node.level == 0:
        return node.module
    try:
        relative = path.relative_to(SRC_ROOT)
    except ValueError:
        return node.module
    package = list(relative.parts[:-1])
    climb = node.level - 1
    if climb > len(package):
        return None
    resolved = package[: len(package) - climb]
    if node.module:
        resolved.extend(node.module.split("."))
    return ".".join(resolved)


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            resolved = _resolved_import_from(path, node)
            if resolved:
                imported.extend(f"{resolved}.{alias.name}" for alias in node.names)
    return imported


def _is_prefixed(import_name: str, prefix: str) -> bool:
    return import_name == prefix or import_name.startswith(f"{prefix}.")


def _matches_any(import_name: str, prefixes: Iterable[str]) -> bool:
    return any(_is_prefixed(import_name, prefix) for prefix in prefixes)


def _cross_module_target(owner: str, import_name: str) -> tuple[str, str | None] | None:
    prefix = "request_engine.modules."
    if not import_name.startswith(prefix):
        return None

    parts = import_name.split(".")
    if len(parts) < 3:
        return None

    target = parts[2]
    if target == owner or target not in ALL_MODULES:
        return None

    surface = parts[3] if len(parts) > 3 else None
    return target, surface


def _actual_dependency_graph() -> dict[str, set[str]]:
    graph: dict[str, set[str]] = {module: set() for module in ALL_MODULES}
    for owner in ALL_MODULES:
        for path in _python_files(MODULES_ROOT / owner):
            for import_name in _imports(path):
                target = _cross_module_target(owner, import_name)
                if target is not None:
                    graph[owner].add(target[0])
    return graph


def _format_violations(title: str, violations: Iterable[str], guidance: str) -> str:
    return "\n".join([title, *[f"- {item}" for item in violations], "", guidance])


def _find_cycle(graph: dict[str, set[str]]) -> tuple[str, ...] | None:
    visiting: set[str] = set()
    visited: set[str] = set()
    path: list[str] = []

    def visit(node: str) -> tuple[str, ...] | None:
        if node in visiting:
            start = path.index(node)
            return tuple([*path[start:], node])
        if node in visited:
            return None

        visiting.add(node)
        path.append(node)
        for target in sorted(graph[node]):
            cycle = visit(target)
            if cycle is not None:
                return cycle
        path.pop()
        visiting.remove(node)
        visited.add(node)
        return None

    for node in sorted(graph):
        cycle = visit(node)
        if cycle is not None:
            return cycle
    return None


def test_relative_cross_module_import_is_not_a_dependency_policy_bypass() -> None:
    path = SRC_ROOT / "request_engine/modules/booking/application/probe.py"
    tree = ast.parse("from ...queue.contracts import QueueRead\n")
    node = tree.body[0]
    assert isinstance(node, ast.ImportFrom)
    assert _resolved_import_from(path, node) == "request_engine.modules.queue.contracts"
    target = _cross_module_target("booking", "request_engine.modules.queue.contracts.QueueRead")
    assert target == ("queue", "contracts")


def test_every_business_module_has_an_explicit_dependency_policy() -> None:
    assert set(MODULE_DEPENDENCY_POLICY) == set(ALL_MODULES), (
        "Business-module inventory changed without an explicit dependency-policy decision. "
        f"actual={sorted(ALL_MODULES)} policy={sorted(MODULE_DEPENDENCY_POLICY)}"
    )


def test_cross_module_imports_use_published_contract_surfaces() -> None:
    violations: list[str] = []
    for owner in ALL_MODULES:
        for path in _python_files(MODULES_ROOT / owner):
            for import_name in _imports(path):
                target = _cross_module_target(owner, import_name)
                if target is None:
                    continue
                target_module, surface = target
                if surface != "contracts":
                    violations.append(
                        f"{path.relative_to(REPO_ROOT)} -> {import_name} "
                        f"(expected request_engine.modules.{target_module}.contracts.*)"
                    )

    assert not violations, _format_violations(
        "Cross-module connection-surface violation.",
        violations,
        "Expose the smallest stable concept from the target module's contracts surface; "
        "do not export domain/application/adapter internals just to satisfy this test.",
    )


def test_module_dependencies_match_approved_direction_policy() -> None:
    violations: list[str] = []
    for owner in ALL_MODULES:
        allowed_targets = MODULE_DEPENDENCY_POLICY[owner]
        for path in _python_files(MODULES_ROOT / owner):
            for import_name in _imports(path):
                target = _cross_module_target(owner, import_name)
                if target is None:
                    continue
                target_module, _ = target
                if target_module not in allowed_targets:
                    violations.append(
                        f"{path.relative_to(REPO_ROOT)} -> {target_module} via {import_name}; "
                        f"approved targets for {owner}: {sorted(allowed_targets)}"
                    )

    assert not violations, _format_violations(
        "Unapproved module dependency.",
        violations,
        "Do not widen MODULE_DEPENDENCY_POLICY as a mechanical fix. First verify ownership, "
        "whether the dependency must be synchronous, and whether an event/outbox boundary is "
        "correct. Update canonical architecture docs when a new edge is accepted.",
    )


def test_actual_module_dependency_graph_is_acyclic() -> None:
    cycle = _find_cycle(_actual_dependency_graph())
    message = (
        "Business-module dependency cycle detected: "
        f"{' -> '.join(cycle or ())}. Revisit ownership or use a one-way surface."
    )
    assert cycle is None, message


def test_domain_layers_do_not_depend_on_outer_layers_or_infrastructure() -> None:
    violations: list[str] = []
    for module in ALL_MODULES:
        forbidden_internal = (
            f"request_engine.modules.{module}.adapters",
            f"request_engine.modules.{module}.api",
            f"request_engine.modules.{module}.application",
            "request_engine.bootstrap",
            "request_engine.entrypoints",
        )
        for path in _python_files(MODULES_ROOT / module / "domain"):
            for import_name in _imports(path):
                if _matches_any(import_name, FRAMEWORK_OR_INFRA_PREFIXES) or _matches_any(
                    import_name, forbidden_internal
                ):
                    violations.append(f"{path.relative_to(REPO_ROOT)} -> {import_name}")

    assert not violations, _format_violations(
        "Domain layer crossed an outer/infrastructure boundary.",
        violations,
        "Keep domain policy framework-free. Move transport/persistence concerns outward and pass "
        "only domain values or explicit application contracts inward.",
    )


def test_application_layers_do_not_import_module_adapters_or_transport() -> None:
    violations: list[str] = []
    for module in ALL_MODULES:
        forbidden_internal = (
            f"request_engine.modules.{module}.adapters",
            f"request_engine.modules.{module}.api",
            "request_engine.bootstrap",
            "request_engine.entrypoints",
        )
        for path in _python_files(MODULES_ROOT / module / "application"):
            for import_name in _imports(path):
                if _matches_any(import_name, FRAMEWORK_OR_INFRA_PREFIXES) or _matches_any(
                    import_name, forbidden_internal
                ):
                    violations.append(f"{path.relative_to(REPO_ROOT)} -> {import_name}")

    assert not violations, _format_violations(
        "Application layer imported a concrete adapter or transport concern.",
        violations,
        "Define/use a Protocol at the application boundary. Concrete PostgreSQL/provider "
        "construction belongs outside the application layer.",
    )


def test_http_routers_depend_on_application_surfaces_not_concrete_adapters() -> None:
    violations: list[str] = []
    for module in ALL_MODULES:
        router = MODULES_ROOT / module / "api" / "router.py"
        if not router.is_file():
            continue
        for import_name in _imports(router):
            if ".adapters." in import_name:
                violations.append(f"{router.relative_to(REPO_ROOT)} -> {import_name}")

    assert not violations, _format_violations(
        "HTTP router depends on a concrete adapter.",
        violations,
        "Type routers against application Protocols. Concrete PostgreSQL/provider construction "
        "belongs in the module-owned install/composition surface, not router.py.",
    )


def test_contract_surfaces_are_dependency_light() -> None:
    violations: list[str] = []
    for module in ALL_MODULES:
        forbidden_internal = (
            f"request_engine.modules.{module}.adapters",
            f"request_engine.modules.{module}.api",
            f"request_engine.modules.{module}.application",
            f"request_engine.modules.{module}.domain",
            "request_engine.bootstrap",
            "request_engine.entrypoints",
        )
        for path in _python_files(MODULES_ROOT / module / "contracts"):
            for import_name in _imports(path):
                if _matches_any(import_name, FRAMEWORK_OR_INFRA_PREFIXES) or _matches_any(
                    import_name, forbidden_internal
                ):
                    violations.append(f"{path.relative_to(REPO_ROOT)} -> {import_name}")

    assert not violations, _format_violations(
        "Published module contract leaked internal/framework dependencies.",
        violations,
        "Contracts must remain stable, dependency-light connection surfaces. Map internal domain "
        "or persistence objects into explicit contract values instead of re-exporting internals.",
    )


def test_database_adapters_do_not_depend_on_http_transport() -> None:
    violations: list[str] = []
    for module in ALL_MODULES:
        db_root = MODULES_ROOT / module / "adapters" / "db"
        forbidden = (
            f"request_engine.modules.{module}.api",
            "request_engine.entrypoints",
            "fastapi",
        )
        for path in _python_files(db_root):
            for import_name in _imports(path):
                if _matches_any(import_name, forbidden):
                    violations.append(f"{path.relative_to(REPO_ROOT)} -> {import_name}")

    assert not violations, _format_violations(
        "Database adapter depends on HTTP transport.",
        violations,
        "Map database rows/errors to application/domain contracts inside the DB adapter. HTTP "
        "DTOs and FastAPI concerns belong outside persistence.",
    )
