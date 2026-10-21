"""Owner-facing names and next steps for onboarding readiness, for display only.

The onboarding API's area keys and resolution hints are written for
integrations; the console says what the person should do in their own terms.
This copy never decides readiness: the onboarding owner does.
"""

from __future__ import annotations

_LABELS = {
    "business_party": "Business identity",
    "locations": "Locations",
    "appointments": "Appointments",
    "walk_in_queue": "Walk-in queue",
    "communications": "Messages",
    "identity": "Sign-in",
    "tenant_control": "Owner control",
    "staff_administration": "Team administration",
    "recovery": "Recovery",
}
# Owner-facing next steps. The onboarding API's resolution hints are written for
# integrations; the console says what the person should do in their own terms.
_GUIDANCE = {
    "business_party": "Your business record is incomplete. Ask your platform administrator.",
    "locations": "Add the place where you see customers, with its opening hours.",
    "appointments": (
        "Add a service with its price, and a person or room with weekly hours, "
        "so customers can book."
    ),
    "walk_in_queue": "Create a waiting line for customers who arrive without an appointment.",
    "communications": "Choose how confirmations and reminders reach your customers.",
    "identity": "Sign-in for this business is not ready. Ask your platform administrator.",
    "tenant_control": "New owner permissions are available. Request the upgrade.",
    "staff_administration": "Team management is not ready. Ask your platform administrator.",
    "recovery": (
        "Save recovery codes in Account security so you can get back in if you lose your password."
    ),
}
_STATES = {"ready": "Ready", "blocked": "To do", "unknown": "Not checked"}


def readiness_label(key: str) -> str:
    return _LABELS.get(key, key.replace("_", " ").capitalize())


def readiness_state(status: str) -> str:
    return _STATES.get(status, status.capitalize())


def readiness_guidance(key: str) -> str:
    return _GUIDANCE.get(key, "")
