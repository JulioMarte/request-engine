"""Plain-language names for capability keys, for display only.

This is interface copy, not policy: it never decides what a capability allows,
who may hold it or whether an agent may use it. Unknown keys fall back to a
readable form of the key itself, so a new owner capability is never hidden.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

_GROUPS: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    (
        "Appointments",
        (
            ("appointments.find_slots", "Find open times"),
            ("appointments.book", "Book appointments"),
            ("appointments.reschedule", "Reschedule appointments"),
            ("appointments.cancel", "Cancel appointments"),
            ("appointments.read", "See appointment details"),
            ("appointments.day_board", "See the day's appointments"),
            ("appointments.confirm_attendance", "Record attendance replies"),
            ("appointments.record_arrival_estimate", "Record arrival estimates"),
            ("appointments.subject_override", "Act for any customer on appointments"),
        ),
    ),
    (
        "Front desk and queues",
        (
            ("queue.list", "See queues"),
            ("queue.status", "See a customer's place in line"),
            ("queue.staff_read", "See the live queue"),
            ("queue.staff_history_read", "See queue history"),
            ("queue.join", "Add customers to a queue"),
            ("queue.leave", "Remove customers from a queue"),
            ("queue.check_in", "Check customers in"),
            ("queue.call_next", "Call the next customer"),
            ("queue.skip", "Skip a customer"),
            ("queue.mark_no_show", "Mark no-shows"),
            ("queue.operator_select", "Choose a specific customer"),
            ("queue.recall_hold", "Hold a customer for recall"),
            ("queue.release_recall_hold", "Release a recall hold"),
            ("queue.classify_expected_workload", "Set expected service length"),
            ("queue.subject_override", "Act for any customer in queues"),
            ("queue.configure", "Configure queues"),
            ("queue.read_configuration", "See queue settings"),
            ("queue.manage_intake", "Open or close queue intake"),
        ),
    ),
    (
        "Service in progress",
        (
            ("service_session.start", "Start a service"),
            ("service_session.pause", "Pause a service"),
            ("service_session.resume", "Resume a service"),
            ("service_session.complete", "Finish a service"),
            ("service_session.read", "See services in progress"),
            ("resource_activity.start", "Start resource activity"),
            ("resource_activity.end", "End resource activity"),
            ("resource_activity.read", "See resource activity"),
            ("workload.list", "See service lengths"),
            ("workload.create", "Add service lengths"),
            ("workload.update", "Change service lengths"),
            ("workload.deactivate", "Retire service lengths"),
        ),
    ),
    (
        "Customers",
        (
            ("parties.register", "Register customers"),
            ("parties.lookup", "Find customers"),
            ("parties.rename", "Rename customers"),
            ("parties.add_contact_point", "Add customer contacts"),
            ("parties.confirm_contact_point", "Confirm customer contacts"),
            ("parties.deactivate_contact_point", "Remove customer contacts"),
            ("parties.add_document", "Add customer documents"),
            ("parties.add_administrative_identifier", "Add customer identifiers"),
            ("parties.lookup_administrative_identifier", "Find customers by identifier"),
            ("parties.read_revisions", "See customer change history"),
            ("parties.deactivate", "Deactivate customers"),
            ("parties.rollback_identity", "Undo customer identity changes"),
        ),
    ),
    (
        "Requests",
        (
            ("requests.submit", "Submit requests"),
            ("requests.read", "See requests"),
            ("requests.read_inbox", "See the request inbox"),
            ("requests.cancel", "Cancel requests"),
            ("requests.read_definitions", "See request types"),
            ("requests.create_definition", "Create request types"),
            ("requests.publish_definition_version", "Publish request types"),
            ("requests.set_definition_active", "Turn request types on or off"),
            ("requests.party_override", "Act for any customer on requests"),
        ),
    ),
    (
        "Business, services and locations",
        (
            ("business.get_info", "See business information"),
            ("organization.manage_profile", "Edit the business profile"),
            ("organization.bootstrap", "Set up the business"),
            ("catalog.search_offerings", "Search services"),
            ("catalog.get_offering_details", "See service details"),
            ("catalog.manage", "Manage services and locations"),
            ("catalog.read_configuration", "See services and locations setup"),
            ("booking.manage_supply", "Manage availability and resources"),
            ("booking.read_supply", "See availability and resources"),
            ("communications.configure", "Configure messages"),
            ("communications.read_configuration", "See message settings"),
            ("discovery.manage", "Manage public listing"),
            ("onboarding.read", "See setup progress"),
        ),
    ),
    (
        "Reminders and waitlist",
        (
            ("reminders.create_plan", "Schedule reminders"),
            ("reminders.cancel_plan", "Cancel reminders"),
            ("reminders.read", "See reminders"),
            ("reminders.subject_override", "Act for any customer on reminders"),
            ("waitlist.join", "Add to the waitlist"),
            ("waitlist.leave", "Remove from the waitlist"),
            ("waitlist.read", "See the waitlist"),
            ("waitlist.accept_offer", "Accept waitlist offers"),
            ("waitlist.decline_offer", "Decline waitlist offers"),
            ("waitlist.subject_override", "Act for any customer on the waitlist"),
        ),
    ),
    (
        "Capacity and recovery",
        (
            ("live_capacity.read", "See live capacity"),
            ("live_capacity.customer_read", "See customer wait estimates"),
            ("live_capacity.evaluate_intake", "Check if more customers fit"),
            ("live_capacity.configure_scope", "Configure capacity tracking"),
            ("live_capacity.configure_estimate", "Configure wait estimates"),
            ("operational_recovery.read", "See recovery plans"),
            ("operational_recovery.propose", "Propose recovery plans"),
            ("operational_recovery.execute", "Run recovery plans"),
            ("operational_recovery.configure_autonomy", "Configure automatic recovery"),
        ),
    ),
    (
        "Team and access",
        (
            ("staff.read", "See the team"),
            ("staff.invite", "Invite people"),
            ("staff.propose_invitation", "Suggest people to invite"),
            ("staff.manage_membership", "Activate or suspend team members"),
            ("staff.manage_authority", "Change team permissions"),
            ("staff.plan_authority", "Preview permission changes"),
            ("staff.manage_own_admin_contact", "Manage own admin contact"),
            ("staff.confirm_own_admin_contact", "Confirm own admin contact"),
            ("authority.read_self", "See own permissions"),
            ("authority.inspect_resource", "Inspect who can act on an item"),
            ("delegation.create", "Delegate tasks"),
            ("delegation.revoke", "Withdraw delegated tasks"),
            ("controller_policy_upgrade", "Upgrade owner permissions"),
            ("identity.bind", "Connect sign-in accounts"),
            ("identity.binding.read", "See connected sign-in accounts"),
            ("identity.link_self", "Link own sign-in accounts"),
            ("identity_exchange.publish", "Publish identity matching"),
            ("identity_exchange.match", "Match identities"),
            ("identity_exchange.adopt", "Adopt matched identities"),
        ),
    ),
    (
        "Agents and integrations",
        (
            ("agent.read", "See agents"),
            ("agent.provision", "Create agents"),
            ("agent.manage_authority", "Change agent permissions and keys"),
            ("agent.manage_policy", "Change agent safety limits"),
            ("agent.policy.read", "See agent safety limits"),
            ("agent.suspend", "Pause or revoke agents"),
            ("integration.read", "See integrations"),
            ("integration.provision", "Create integrations"),
            ("integration.manage_authority", "Change integration permissions and keys"),
            ("integration.suspend", "Pause or revoke integrations"),
            ("operational_copilot.read", "Use legacy assistant reads"),
            ("operational_copilot.interpret", "Use legacy assistant interpretation"),
            ("operational_copilot.execute", "Use legacy assistant actions"),
        ),
    ),
)

_BY_KEY: dict[str, tuple[str, str]] = {
    key: (group, label) for group, entries in _GROUPS for key, label in entries
}
_GROUP_ORDER = {group: index for index, (group, _) in enumerate(_GROUPS)}
_OTHER = "Other"


@dataclass(frozen=True)
class CapabilityLabel:
    key: str
    group: str
    label: str


def capability_label(key: str) -> CapabilityLabel:
    group, label = _BY_KEY.get(key, (_OTHER, key.replace("_", " ").replace(".", ": ").capitalize()))
    return CapabilityLabel(key=key, group=group, label=label)


def grouped_capabilities(keys: Iterable[str]) -> list[tuple[str, list[CapabilityLabel]]]:
    """Group keys for display, keeping the owner's keys intact as data."""

    grouped: dict[str, list[CapabilityLabel]] = {}
    for key in sorted(set(keys)):
        item = capability_label(key)
        grouped.setdefault(item.group, []).append(item)
    order = sorted(grouped, key=lambda group: _GROUP_ORDER.get(group, len(_GROUP_ORDER)))
    return [(group, sorted(grouped[group], key=lambda item: item.label)) for group in order]


__all__ = ["CapabilityLabel", "capability_label", "grouped_capabilities"]
