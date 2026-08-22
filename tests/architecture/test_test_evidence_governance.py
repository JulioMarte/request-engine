from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GUIDE = "docs/testing/evidence-authoring-guide.md"


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_evidence_authoring_guide_is_discoverable_by_agents_and_contributors() -> None:
    assert (ROOT / GUIDE).is_file()
    assert GUIDE in _source("tests/AGENTS.md")
    assert GUIDE in _source("CONTRIBUTING.md")
    assert GUIDE in _source(".github/instructions/python.instructions.md")
    assert "evidence-authoring-guide.md" in _source("docs/testing/README.md")
    assert GUIDE in _source("tests/fixtures/README.md")


def test_evidence_guide_requires_falsifiable_real_postgres_proofs() -> None:
    guide = _source(GUIDE)

    assert "capable of failing" in guide
    assert "real PostgreSQL 18" in guide
    assert "complete and valid business world" in guide
    assert "not** permission to manufacture the result being tested" in guide
    assert "independent connections/Sessions/transactions" in guide


def test_postgres_suite_has_automatic_data_isolation() -> None:
    conftest = _source("tests/conftest.py")

    assert "isolate_postgres_test_data" in conftest
    assert 'get_closest_marker("postgres")' in conftest
    assert "TRUNCATE TABLE" in conftest
