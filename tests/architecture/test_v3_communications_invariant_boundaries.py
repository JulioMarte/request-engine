import ast
from pathlib import Path


def _source(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_i47_delivery_status_is_confined_to_communications_state() -> None:
    paths = (
        "src/request_engine/modules/communications/adapters/worker/delivery_worker.py",
        "src/request_engine/modules/communications/adapters/db/delivery_store.py",
    )
    forbidden_module_prefixes = (
        "request_engine.modules.booking",
        "request_engine.modules.queue",
        "request_engine.modules.requests",
    )
    forbidden_authoritative_tables = (
        "request_engine.reservations",
        "request_engine.capacity_claims",
        "request_engine.capacity_holds",
        "request_engine.queue_entries",
        "request_engine.service_queues",
        "request_engine.waitlist_entries",
        "request_engine.slot_opportunities",
        "request_engine.requests",
    )

    for path in paths:
        source = _source(path)
        for prefix in forbidden_module_prefixes:
            assert prefix not in source, f"{path} crosses domain boundary via {prefix}"
        for table in forbidden_authoritative_tables:
            assert table not in source, f"{path} mutates unrelated authoritative table {table}"


def test_i51_medication_reminder_execution_cannot_infer_clinical_instruction() -> None:
    path = "src/request_engine/modules/communications/adapters/db/reminder_occurrences.py"
    source = _source(path)
    tree = ast.parse(source)

    forbidden_clinical_terms = (
        "dosage",
        "dose_amount",
        "medication_name",
        "prescription",
        "clinical_instruction",
        "treatment_plan",
    )
    lowered = source.lower()
    for term in forbidden_clinical_terms:
        assert term not in lowered, f"reminder execution acquired clinical inference field {term}"

    intents = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "CommunicationTaskIntent"
    ]
    assert len(intents) == 1
    intent = intents[0]
    keywords = {item.arg: item.value for item in intent.keywords if item.arg is not None}

    render_context = keywords.get("render_context")
    assert isinstance(render_context, ast.Dict)
    render_keys = {
        key.value
        for key in render_context.keys
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }
    assert render_keys == {"reminder_plan_id", "plan_revision", "occurrence_at"}

    assert ast.unparse(keywords["purpose"]) == "plan.purpose"
    assert ast.unparse(keywords["template_key"]) == "plan.template_key"
    assert ast.unparse(keywords["template_version"]) == "plan.template_version"
