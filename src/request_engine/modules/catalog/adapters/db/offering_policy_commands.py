import json
from typing import Literal, cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.catalog.application.commands import (
    set_offering_version_booking_policy as policy_commands,
)
from request_engine.modules.catalog.application.commands.bootstrap_catalog import (
    ChannelPolicyInput,
)
from request_engine.modules.catalog.application.errors import (
    CatalogConfigurationConflict,
    OfferingBookingPolicyRevisionConflict,
)
from request_engine.platform.audit.postgres import append_audit
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)
from request_engine.platform.security.operational_authority import (
    MANAGE_COMMERCIAL_TERMS_SCOPE,
    require_operational_authority,
)

_CAPABILITY = "catalog.set_offering_version_booking_policy"


class PostgresOfferingBookingPolicyCommands:
    """Append booking-policy override revisions for future reservations."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def set_offering_version_booking_policy(
        self, command: policy_commands.SetOfferingVersionBookingPolicyCommand
    ) -> policy_commands.OfferingVersionBookingPolicyState:
        policy = policy_commands.booking_policy_json(command.policy)
        fingerprint = command_fingerprint(
            _CAPABILITY,
            {
                "authority_party_id": command.authority_party_id,
                "offering_version_id": command.offering_version_id,
                "expected_revision": command.expected_revision,
                "booking_policy": policy,
            },
        )
        try:
            async with tenant_transaction(
                self._session_factory, command.organization_id
            ) as session:
                idempotency_id, replay = await acquire_idempotency(
                    session,
                    organization_id=command.organization_id,
                    principal_id=command.principal_id,
                    capability=_CAPABILITY,
                    idempotency_key=command.idempotency_key,
                    fingerprint=fingerprint,
                )
                if replay is not None:
                    return _state_from_json(
                        command.offering_version_id,
                        cast(dict[str, object], replay["policy"]),
                    )

                authority = await require_operational_authority(
                    session,
                    organization_id=command.organization_id,
                    principal_id=command.principal_id,
                    authority_party_id=command.authority_party_id,
                    scope_key=MANAGE_COMMERCIAL_TERMS_SCOPE,
                )
                offering = (
                    (
                        await session.execute(
                            text(
                                """
                                SELECT ov.id
                                FROM request_engine.offering_versions ov
                                JOIN request_engine.offerings o
                                  ON o.organization_id = ov.organization_id
                                 AND o.id = ov.offering_id
                                WHERE ov.organization_id = :organization_id
                                  AND ov.id = :offering_version_id
                                  AND o.active
                                FOR UPDATE OF o
                                """
                            ),
                            {
                                "organization_id": command.organization_id,
                                "offering_version_id": command.offering_version_id,
                            },
                        )
                    )
                    .mappings()
                    .first()
                )
                if offering is None:
                    raise CatalogConfigurationConflict(
                        "OfferingVersion is missing, inactive, or belongs to another Organization"
                    )
                current_revision = await _current_policy_revision(
                    session,
                    organization_id=command.organization_id,
                    offering_version_id=command.offering_version_id,
                )
                if current_revision != command.expected_revision:
                    raise OfferingBookingPolicyRevisionConflict(
                        command.offering_version_id,
                        command.expected_revision,
                        current_revision,
                    )

                new_revision = current_revision + 1
                row = (
                    (
                        await session.execute(
                            text(
                                """
                                INSERT INTO request_engine.offering_version_booking_policies (
                                    organization_id, offering_version_id, revision,
                                    booking_policy
                                ) VALUES (
                                    :organization_id, :offering_version_id, :revision,
                                    CAST(:booking_policy AS jsonb)
                                )
                                RETURNING id
                                """
                            ),
                            {
                                "organization_id": command.organization_id,
                                "offering_version_id": command.offering_version_id,
                                "revision": new_revision,
                                "booking_policy": json.dumps(policy, separators=(",", ":")),
                            },
                        )
                    )
                    .mappings()
                    .one()
                )
                state = policy_commands.OfferingVersionBookingPolicyState(
                    offering_version_id=command.offering_version_id,
                    booking_policy_revision=new_revision,
                    policy=command.policy,
                )
                await append_audit(
                    session,
                    organization_id=command.organization_id,
                    principal_id=command.principal_id,
                    command_name=_CAPABILITY,
                    aggregate_kind="OfferingVersionBookingPolicy",
                    aggregate_id=cast(UUID, row["id"]),
                    idempotency_id=idempotency_id,
                    details={
                        "authority": authority.audit_details(),
                        "offering_version_id": str(command.offering_version_id),
                        "previous_revision": current_revision,
                        "booking_policy_revision": new_revision,
                    },
                )
                await complete_idempotency(
                    session,
                    idempotency_id,
                    {
                        "policy": {
                            "booking_policy_revision": new_revision,
                            "booking_policy": policy,
                        }
                    },
                )
                return state
        except IntegrityError as exc:
            if getattr(exc.orig, "sqlstate", None) == "23505":
                raise CatalogConfigurationConflict(
                    "OfferingVersion booking policy revision already exists"
                ) from None
            raise


async def _current_policy_revision(
    session: AsyncSession,
    *,
    organization_id: UUID,
    offering_version_id: UUID,
) -> int:
    return cast(
        int,
        (
            await session.execute(
                text(
                    """
                    SELECT COALESCE(max(revision), 0)
                    FROM request_engine.offering_version_booking_policies
                    WHERE organization_id = :organization_id
                      AND offering_version_id = :offering_version_id
                    """
                ),
                {
                    "organization_id": organization_id,
                    "offering_version_id": offering_version_id,
                },
            )
        ).scalar_one(),
    )


def _state_from_json(
    offering_version_id: UUID,
    value: dict[str, object],
) -> policy_commands.OfferingVersionBookingPolicyState:
    return policy_commands.OfferingVersionBookingPolicyState(
        offering_version_id=offering_version_id,
        booking_policy_revision=cast(int, value["booking_policy_revision"]),
        policy=_policy_input_from_json(
            cast(dict[str, object], value["booking_policy"]),
        ),
    )


def _policy_input_from_json(policy: dict[str, object]) -> policy_commands.BookingPolicyInput:
    attendance = cast(dict[str, object], policy.get("attendance", {}))
    communications = cast(dict[str, object], policy.get("communications", {}))
    recovery = cast(dict[str, object], policy.get("slot_recovery", {}))
    channel_raw = cast(dict[str, object] | None, communications.get("channel_policy") or None)
    channel_policy: ChannelPolicyInput | None = None
    if channel_raw:
        channel_policy = ChannelPolicyInput(
            channels=tuple(
                cast(Literal["email", "phone", "sms", "voice", "whatsapp"], item)
                for item in cast(list[object], channel_raw.get("channels", ()))
            ),
            provider_key=cast(str | None, channel_raw.get("provider_key")),
            reconcile_after_seconds=cast(int, channel_raw.get("reconcile_after_seconds", 300)),
            retry_after_seconds=cast(int, channel_raw.get("retry_after_seconds", 60)),
        )
    reminders = cast(list[object], communications.get("reminders_before_minutes", ()))
    no_show = attendance.get("no_show_after_minutes")
    attendance_request = attendance.get("attendance_request_before_minutes")
    return policy_commands.BookingPolicyInput(
        slot_step_minutes=cast(int, policy.get("slot_step_minutes", 30)),
        attendance=policy_commands.BookingAttendancePolicyInput(
            confirmation_required=bool(attendance.get("confirmation_required", False)),
            attendance_request_before_minutes=(
                cast(int, attendance_request) if attendance_request is not None else None
            ),
            decline_action=cast(
                Literal["keep", "cancel"], attendance.get("decline_action", "keep")
            ),
            no_response_action=cast(Literal["keep"], attendance.get("no_response_action", "keep")),
            no_show_after_minutes=cast(int, no_show) if no_show is not None else None,
        ),
        communications=policy_commands.BookingCommunicationsPolicyInput(
            confirmation=bool(communications.get("confirmation", False)),
            reminders_before_minutes=tuple(cast(int, item) for item in reminders),
            channel_policy=channel_policy,
        ),
        slot_recovery=policy_commands.BookingSlotRecoveryPolicyInput(
            enabled=bool(recovery.get("enabled", False)),
            minimum_lead_minutes=cast(int, recovery.get("minimum_lead_minutes", 30)),
        ),
    )
