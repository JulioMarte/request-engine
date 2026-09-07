from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
POLICY = REPO_ROOT / "docs" / "architecture" / "continuous-evolution-policy.md"
SYSTEM_MODE = REPO_ROOT / "docs" / "architecture" / "system-optimization-mode.md"
DOCS_INDEX = REPO_ROOT / "docs" / "README.md"
MIGRATIONS_README = REPO_ROOT / "migrations" / "README.md"
MIGRATIONS_AGENTS = REPO_ROOT / "migrations" / "AGENTS.md"
ROOT_AGENTS = REPO_ROOT / "AGENTS.md"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_permanent_evolution_policy_is_discoverable_from_current_authority() -> None:
    assert POLICY.is_file()

    policy_ref = "continuous-evolution-policy.md"
    assert policy_ref in _text(SYSTEM_MODE)
    assert policy_ref in _text(DOCS_INDEX)
    assert policy_ref in _text(MIGRATIONS_README)
    assert policy_ref in _text(MIGRATIONS_AGENTS)

    # Root instructions intentionally remain a concise router: they point first
    # to system optimization mode, which must in turn route to permanent policy.
    assert "system-optimization-mode.md" in _text(ROOT_AGENTS)


def test_current_product_evolution_is_not_pinned_to_accepted_0001() -> None:
    policy = _text(POLICY)
    migration_docs = _text(MIGRATIONS_README)
    migration_agents = _text(MIGRATIONS_AGENTS)

    for text in (policy, migration_docs, migration_agents):
        assert "immutable history" in text.lower()
        assert "evolvable future" in text.lower()
        assert "0002+" in text

    assert "HEAD == 0001" in migration_docs
    assert "current head to remain a specific revision forever" in migration_agents


def test_evolution_policy_requires_transition_safety_not_structural_freeze() -> None:
    policy = _text(POLICY).lower()

    assert "expand → migrate → contract" in policy
    assert "customer-owned production data" in policy
    assert "published/external contract change" in policy
    assert "bad permanent gates" in policy
    assert "exact schema/module/file/endpoint inventories" in policy
    assert "rebaseline is not a cleanup technique" in policy
