from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULES_ROOT = ROOT / "src" / "request_engine" / "modules"

IMPORTANT_INSTRUCTION_BOUNDARIES = (
    ROOT,
    ROOT / "docs",
    ROOT / "migrations",
    MODULES_ROOT,
    ROOT / "tests",
)

FORBIDDEN_BUSINESS_LAYER_IMPORTS = ("pydantic",)
TRANSPORT_SUFFIXES = ("Body", "View", "Params")
FORBIDDEN_CONTRACT_SUFFIXES = ("Body", "View", "Row", "ORM")
FORBIDDEN_GENERIC_BUSINESS_FILES = {
    "services.py",
    "managers.py",
    "helpers.py",
    "utils.py",
    "common.py",
}


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


def _class_names(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]


def _base_model_classes(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        base_names = {base.id for base in node.bases if isinstance(base, ast.Name)} | {
            base.attr for base in node.bases if isinstance(base, ast.Attribute)
        }
        if "BaseModel" in base_names:
            names.append(node.name)
    return names


def _is_prefixed(import_name: str, prefix: str) -> bool:
    return import_name == prefix or import_name.startswith(f"{prefix}.")


def test_business_semantic_layers_do_not_use_pydantic_transport_types() -> None:
    violations: list[str] = []
    for module_root in (path for path in MODULES_ROOT.iterdir() if path.is_dir()):
        for layer in ("domain", "application", "contracts"):
            for path in _python_files(module_root / layer):
                for import_name in _imports(path):
                    if any(
                        _is_prefixed(import_name, prefix)
                        for prefix in FORBIDDEN_BUSINESS_LAYER_IMPORTS
                    ):
                        violations.append(f"{path.relative_to(ROOT)} -> {import_name}")

    assert violations == [], (
        "Pydantic transport/configuration types leaked into a business semantic layer. "
        "Keep domain/application/contracts framework-free and map at the API boundary:\n"
        + "\n".join(f"- {item}" for item in violations)
    )


def test_http_transport_model_names_make_the_boundary_visible() -> None:
    violations: list[str] = []
    for api_root in MODULES_ROOT.glob("*/api"):
        for path in _python_files(api_root):
            for class_name in _base_model_classes(path):
                if not class_name.endswith(TRANSPORT_SUFFIXES):
                    violations.append(f"{path.relative_to(ROOT)}::{class_name}")

    assert violations == [], (
        "HTTP transport Pydantic models must use a transport-explicit suffix "
        f"{TRANSPORT_SUFFIXES}; change the convention only with the repository governance contract:\n"
        + "\n".join(f"- {item}" for item in violations)
    )


def test_cross_module_contract_names_do_not_masquerade_as_transport_or_rows() -> None:
    violations: list[str] = []
    for contracts_root in MODULES_ROOT.glob("*/contracts"):
        for path in _python_files(contracts_root):
            for class_name in _class_names(path):
                if class_name.endswith(FORBIDDEN_CONTRACT_SUFFIXES):
                    violations.append(f"{path.relative_to(ROOT)}::{class_name}")

    assert violations == [], (
        "Published contracts must use business language, not HTTP/persistence type names:\n"
        + "\n".join(f"- {item}" for item in violations)
    )


def test_modules_do_not_gain_generic_business_dumping_ground_files() -> None:
    violations: list[str] = []
    for module_root in (path for path in MODULES_ROOT.iterdir() if path.is_dir()):
        for path in _python_files(module_root):
            if path.name in FORBIDDEN_GENERIC_BUSINESS_FILES:
                violations.append(str(path.relative_to(ROOT)))

    assert violations == [], (
        "Generic business dumping-ground files erase capability ownership. Use a semantic name/layer:\n"
        + "\n".join(f"- {item}" for item in violations)
    )


def test_llm_instruction_adapters_route_through_agents_contracts() -> None:
    violations: list[str] = []
    for boundary in IMPORTANT_INSTRUCTION_BOUNDARIES:
        agents = boundary / "AGENTS.md"
        claude = boundary / "CLAUDE.md"
        gemini = boundary / "GEMINI.md"
        if not agents.is_file():
            violations.append(f"missing {agents.relative_to(ROOT)}")
            continue
        for adapter in (claude, gemini):
            if not adapter.is_file():
                violations.append(f"missing {adapter.relative_to(ROOT)}")
                continue
            source = adapter.read_text(encoding="utf-8")
            if "AGENTS.md" not in source:
                violations.append(
                    f"{adapter.relative_to(ROOT)} does not route through its AGENTS.md contract"
                )

    assert violations == [], (
        "LLM instruction routing drifted. Keep AGENTS.md as the operational contract and "
        "Claude/Gemini files as adapters:\n" + "\n".join(f"- {item}" for item in violations)
    )


def test_copilot_adapter_routes_to_current_authority_not_v2_contracts() -> None:
    copilot = (ROOT / ".github" / "copilot-instructions.md").read_text(encoding="utf-8")

    assert "AGENTS.md" in copilot
    assert "docs/README.md" in copilot
    assert "docs/testing/repository-governance-contract.md" in copilot
    assert "docs/v3/02-pre-sql-contract.md" in copilot
    assert "docs/02-pre-sql-domain-contract.md" not in copilot


def test_path_specific_agent_rules_include_type_and_document_governance() -> None:
    python_rules = (ROOT / ".github" / "instructions" / "python.instructions.md").read_text(
        encoding="utf-8"
    )
    docs_rules = (ROOT / ".github" / "instructions" / "docs.instructions.md").read_text(
        encoding="utf-8"
    )

    assert "repository-governance-contract.md" in python_rules
    assert "Pydantic" in python_rules
    assert "repository-governance-contract.md" in docs_rules
    assert "docs/README.md" in docs_rules


def test_governance_contract_is_discoverable_from_test_and_docs_agent_maps() -> None:
    required_reference = "testing/repository-governance-contract.md"
    docs_agents = (ROOT / "docs" / "AGENTS.md").read_text(encoding="utf-8")
    tests_agents = (ROOT / "tests" / "AGENTS.md").read_text(encoding="utf-8")

    assert required_reference in docs_agents
    assert "repository-governance-contract.md" in tests_agents
