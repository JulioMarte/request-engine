"""Dispatch ScheduledAction vocabulary shared by the delivery execution surfaces.

Lives outside ``delivery_store`` so the escalation adapters can schedule a
child task's initial dispatch without importing the delivery store.
"""

DISPATCH_ACTION_TYPE = "dispatch_task"
DISPATCH_ACTION_VERSION = 1
