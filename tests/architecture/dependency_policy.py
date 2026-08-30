# Approved synchronous Python dependency directions. An allowed edge still has to
# use the target module's contracts surface; it is permission, not ownership.
# New business modules must be added here deliberately; the dependency-policy test
# discovers the module inventory so an unlisted module cannot escape fitness checks.

MODULE_DEPENDENCY_POLICY: dict[str, frozenset[str]] = {
    "tenancy": frozenset(),
    "catalog": frozenset(),
    "requests": frozenset({"tenancy"}),
    "booking": frozenset({"catalog", "tenancy"}),
    "queue": frozenset({"booking", "tenancy"}),
    "communications": frozenset({"booking"}),
    "discovery": frozenset({"booking"}),
    "delivery": frozenset(),
    "live_capacity": frozenset({"booking", "delivery", "queue"}),
    "operational_recovery": frozenset({"booking", "communications", "live_capacity"}),
    "operational_copilot": frozenset(
        {"catalog", "discovery", "live_capacity", "operational_recovery", "queue", "tenancy"}
    ),
    "payments": frozenset(),
    "dispatch": frozenset(),
}

FRAMEWORK_OR_INFRA_PREFIXES = (
    "asyncpg",
    "fastapi",
    "psycopg",
    "sqlalchemy",
)
