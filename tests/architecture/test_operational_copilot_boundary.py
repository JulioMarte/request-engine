import ast
from pathlib import Path

PARSER = Path("src/request_engine/modules/operational_copilot/parser.py")
FORBIDDEN_IMPORT_PARTS = (
    ".application",
    ".adapters",
    "sqlalchemy",
    "asyncpg",
    "psycopg",
)


def test_operational_copilot_parser_has_no_mutation_dependencies() -> None:
    source = PARSER.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = [
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    ]
    imports.extend(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )

    assert not [
        imported
        for imported in imports
        if any(part in imported for part in FORBIDDEN_IMPORT_PARTS)
    ]
