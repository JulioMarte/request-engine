POLICY = "docs/architecture/continuous-evolution-policy.md"
SYSTEM_MODE = "docs/architecture/system-optimization-mode.md"
DOCS_INDEX = "docs/README.md"
MIGRATIONS_README = "migrations/README.md"
MIGRATIONS_AGENTS = "migrations/AGENTS.md"
ROOT_AGENTS = "AGENTS.md"


def _text(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def test_permanent_evolution_policy_is_discoverable_from_current_authority() -> None:
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
    assert "frozen endpoint/module/file inventories" in policy
    assert "present compatibility reason" in policy
    assert "rebaseline" in policy
    assert "cleanup technique" in policy
    assert "production migration" in policy
