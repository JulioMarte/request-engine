from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src" / "request_engine"

EXPECTED_MODULES = {
    "tenancy",
    "catalog",
    "requests",
    "booking",
    "delivery",
    "payments",
    "dispatch",
}

FORBIDDEN_HORIZONTAL_ROOTS = {
    "api",
    "application",
    "domain",
    "infrastructure",
    "workers",
}

DESIGN_CHAIN = [
    "03-postgresql-schema.sql",
    "04-postgresql-v2.7-hardening.sql",
    "05-postgresql-v2.8-hardening.sql",
    "06-postgresql-v2.9-integrity.sql",
    "08-postgresql-v2.10-access-surface.sql",
]


def test_business_modules_have_explicit_ownership_docs() -> None:
    modules_root = SRC_ROOT / "modules"
    actual_modules = {
        path.name
        for path in modules_root.iterdir()
        if path.is_dir() and not path.name.startswith("__")
    }

    assert actual_modules == EXPECTED_MODULES
    for module_name in EXPECTED_MODULES:
        assert (modules_root / module_name / "README.md").is_file()


def test_horizontal_business_layer_roots_do_not_reappear() -> None:
    unexpected = {name for name in FORBIDDEN_HORIZONTAL_ROOTS if (SRC_ROOT / name).exists()}
    assert unexpected == set()


def test_executable_sql_is_owned_by_migrations_not_docs() -> None:
    sql_in_docs = list((REPO_ROOT / "docs").glob("**/*.sql"))
    assert sql_in_docs == []

    design_root = REPO_ROOT / "migrations" / "sql" / "design_chain"
    assert [path.name for path in sorted(design_root.glob("*.sql"))] == DESIGN_CHAIN


def test_agent_guidance_exists_at_important_boundaries() -> None:
    required = [
        REPO_ROOT / "AGENTS.md",
        REPO_ROOT / "docs" / "AGENTS.md",
        REPO_ROOT / "migrations" / "AGENTS.md",
        SRC_ROOT / "modules" / "AGENTS.md",
        REPO_ROOT / "tests" / "AGENTS.md",
    ]
    assert all(path.is_file() for path in required)
