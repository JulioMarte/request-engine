from pathlib import Path

BUSINESS_MODULES = (
    Path("src/request_engine/modules/booking"),
    Path("src/request_engine/modules/queue"),
    Path("src/request_engine/modules/requests"),
)


def test_i44_business_modules_cannot_import_communication_provider_io() -> None:
    forbidden = (
        "request_engine.modules.communications.adapters.worker.delivery_worker",
        "request_engine.modules.communications.contracts.delivery",
        "CommunicationDeliveryProvider",
        "ProviderSendRequest",
        "ProviderLookupRequest",
    )

    offenders: list[str] = []
    for root in BUSINESS_MODULES:
        for path in sorted(root.rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            for token in forbidden:
                if token in source:
                    offenders.append(f"{path}: {token}")

    assert offenders == [], (
        "authoritative business modules acquired direct communication provider I/O: "
        + "; ".join(offenders)
    )


def test_i50_reminder_plan_mutation_surface_is_create_or_cancel_only() -> None:
    commands_dir = Path("src/request_engine/modules/communications/application/commands")
    reminder_command_files = sorted(
        path.name for path in commands_dir.glob("*_reminder_plan.py") if path.is_file()
    )
    assert reminder_command_files == [
        "cancel_reminder_plan.py",
        "create_reminder_plan.py",
    ], (
        "ReminderPlan gained a new mutation surface. Any update/reschedule command must first "
        "prove obsolete ScheduledAction/CommunicationTask invalidation and immutable delivered "
        f"history before this boundary can change: {reminder_command_files}"
    )

    adapter_source = Path(
        "src/request_engine/modules/communications/adapters/db/reminder_commands.py"
    ).read_text(encoding="utf-8")
    assert "update_reminder_plan" not in adapter_source
    assert "reschedule_reminder_plan" not in adapter_source
