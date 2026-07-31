import { v } from "convex/values"
import type { Doc, Id } from "./_generated/dataModel"
import type { MutationCtx } from "./_generated/server"
import { internalMutation, query } from "./_generated/server"
import { bookingStatus } from "./domainValidators"
import { fail } from "./lib/errors"
import { publicId } from "./lib/ids"
import { canAutoRelease, intervalsOverlap } from "./lib/confirmationPolicy"
import { clampToContactWindow } from "./lib/time"

const activeStatuses = new Set(["pending_confirmation", "confirmed", "checked_in", "in_service"])

async function assertOrganizationPrincipal(ctx: MutationCtx, organizationId: Id<"organizations">, principalId: Id<"principals">) {
  const principal = await ctx.db.get(principalId)
  if (!principal || principal.status !== "active") fail("AUTHENTICATION_REQUIRED", "Principal is not active")
  if (principal.type !== "platform" && principal.organizationId !== organizationId) fail("TENANT_SCOPE_VIOLATION", "Principal is outside the organization")
  return principal
}

async function ensureOfferAvailable(ctx: MutationCtx, offer: Doc<"availabilityOffers">, service: Doc<"services">, excludedBookingId?: Id<"bookings">) {
  if (offer.consumedAt) fail("OFFER_ALREADY_CONSUMED", "Availability offer has already been used")
  if (offer.expiresAt <= Date.now()) fail("OFFER_EXPIRED", "Availability offer expired; request fresh options")
  if (offer.sessionId) {
    const session = await ctx.db.get(offer.sessionId)
    if (!session || session.status !== "scheduled" || session.reservedCount + offer.capacityUnits > session.capacity) fail("CAPACITY_EXCEEDED", "Class session no longer has enough capacity")
  } else {
    const bookings = await ctx.db.query("bookings").withIndex("by_organization_start", (q) => q.eq("organizationId", offer.organizationId).lt("startsAt", offer.endsAt)).collect()
    const used = bookings.filter((booking) => booking._id !== excludedBookingId && booking.serviceId === offer.serviceId && activeStatuses.has(booking.status) && booking.endsAt > offer.startsAt).reduce((sum, booking) => sum + booking.capacityUnits, 0)
    if (used + offer.capacityUnits > service.capacity) fail("CAPACITY_EXCEEDED", "The service no longer has enough capacity")
  }
  for (const resourceId of offer.resourceIds) {
    const allocations = await ctx.db.query("bookingAllocations").withIndex("by_resource_date_start", (q) => q.eq("resourceId", resourceId).eq("localDate", offer.localDate)).collect()
    if (allocations.some((allocation) => allocation.bookingId !== excludedBookingId && allocation.status === "held" && intervalsOverlap(allocation.startsAt, allocation.endsAt, offer.startsAt - service.bufferBeforeMinutes * 60_000, offer.endsAt + service.bufferAfterMinutes * 60_000))) {
      fail("SLOT_UNAVAILABLE", "A required resource is no longer available", { retryAvailability: true })
    }
  }
}

async function emitEvent(ctx: MutationCtx, organizationId: Id<"organizations">, booking: Doc<"bookings">, eventType: string, eventActor: { principalId?: Id<"principals">, type: "platform" | "organization" | "agent" | "integration" | "human", label?: string }, fromStatus?: Doc<"bookings">["status"], reason?: string) {
  const now = Date.now()
  await ctx.db.insert("bookingEvents", { organizationId, bookingId: booking._id, eventType, fromStatus, toStatus: booking.status, actor: eventActor, reason, data: {}, occurredAt: now })
  await ctx.db.insert("outboxEvents", { eventId: publicId("evt", `${booking._id}_${now}_${eventType}`), eventType, version: 1, organizationId, aggregateType: "booking", aggregatePublicId: booking.publicId, payload: { bookingId: booking.publicId, status: booking.status }, status: "pending", attempts: 0, availableAt: now, occurredAt: now, updatedAt: now })
}

export const create = internalMutation({
  args: {
    principalId: v.id("principals"), organizationPublicId: v.string(), offerId: v.string(), idempotencyKey: v.string(), requestHash: v.string(),
    bookerPersonPublicId: v.string(), participantPersonPublicIds: v.array(v.string()), patientWarnedAboutAutoRelease: v.boolean(),
    source: v.union(v.literal("agent"), v.literal("panel"), v.literal("api"), v.literal("walk_in")),
  },
  returns: v.object({ bookingId: v.string(), status: bookingStatus, startsAt: v.string(), endsAt: v.string(), confirmationDeadlineAt: v.optional(v.string()), idempotentReplay: v.boolean() }),
  handler: async (ctx, args) => {
    const organization = await ctx.db.query("organizations").withIndex("by_public_id", (q) => q.eq("publicId", args.organizationPublicId)).unique()
    if (!organization) fail("NOT_FOUND", "Organization not found")
    const principal = await assertOrganizationPrincipal(ctx, organization._id, args.principalId)
    const replay = await ctx.db.query("idempotencyKeys").withIndex("by_scope_key", (q) => q.eq("organizationId", organization._id).eq("principalId", principal._id).eq("operation", "booking.create").eq("key", args.idempotencyKey)).unique()
    if (replay) {
      if (replay.requestHash !== args.requestHash) fail("IDEMPOTENCY_CONFLICT", "Idempotency key was used with a different request")
      const booking = await ctx.db.query("bookings").withIndex("by_public_id", (q) => q.eq("publicId", replay.resourcePublicId)).unique()
      if (!booking) fail("NOT_FOUND", "Idempotent booking result no longer exists")
      return { bookingId: booking.publicId, status: booking.status, startsAt: new Date(booking.startsAt).toISOString(), endsAt: new Date(booking.endsAt).toISOString(), confirmationDeadlineAt: booking.confirmationDeadlineAt ? new Date(booking.confirmationDeadlineAt).toISOString() : undefined, idempotentReplay: true as const }
    }
    const offer = await ctx.db.query("availabilityOffers").withIndex("by_public_id", (q) => q.eq("publicId", args.offerId)).unique()
    if (!offer) fail("NOT_FOUND", "Availability offer not found")
    if (offer.organizationId !== organization._id) fail("TENANT_SCOPE_VIOLATION", "Offer is outside the organization")
    const service = await ctx.db.get(offer.serviceId)
    if (!service) fail("NOT_FOUND", "Service not found")
    if (service.autoReleaseUnconfirmed && !service.neverAutoCancel && !args.patientWarnedAboutAutoRelease) fail("MISSING_REQUIRED_FIELDS", "The patient or guardian must be warned about automatic release")
    const booker = await ctx.db.query("people").withIndex("by_public_id", (q) => q.eq("publicId", args.bookerPersonPublicId)).unique()
    if (!booker || booker.organizationId !== organization._id) fail("TENANT_SCOPE_VIOLATION", "Booker is outside the organization")
    const participantIds = [...new Set(args.participantPersonPublicIds.length ? args.participantPersonPublicIds : [args.bookerPersonPublicId])]
    const participants = await Promise.all(participantIds.map((id) => ctx.db.query("people").withIndex("by_public_id", (q) => q.eq("publicId", id)).unique()))
    if (participants.some((person) => !person || person.organizationId !== organization._id)) fail("TENANT_SCOPE_VIOLATION", "A participant is outside the organization")
    if (participants.length !== offer.capacityUnits) fail("MISSING_REQUIRED_FIELDS", "Participant count must match the offered capacity")
    await ensureOfferAvailable(ctx, offer, service)
    const now = Date.now()
    const location = offer.locationId ? await ctx.db.get(offer.locationId) : null
    const confirmationDeadlineAt = service.autoReleaseUnconfirmed && !service.neverAutoCancel && offer.startsAt - now > 2 * 60 * 60_000 ? Math.max(now + 60 * 60_000, offer.startsAt - 24 * 60 * 60_000) : undefined
    const bookingId = await ctx.db.insert("bookings", {
      publicId: "pending", organizationId: organization._id, serviceId: service._id, locationId: offer.locationId, sessionId: offer.sessionId,
      bookerPersonId: booker._id, status: "pending_confirmation", bookingMode: offer.bookingMode, modality: offer.snapshot.modality,
      startsAt: offer.startsAt, endsAt: offer.endsAt, localDate: offer.localDate, timezone: offer.timezone, shift: offer.shift, capacityUnits: offer.capacityUnits,
      snapshot: { serviceName: offer.snapshot.serviceName, durationMinutes: offer.snapshot.durationMinutes, bufferBeforeMinutes: service.bufferBeforeMinutes, bufferAfterMinutes: service.bufferAfterMinutes, locationName: location?.name, price: offer.snapshot.price },
      confirmationDeadlineAt, patientWarnedAboutAutoRelease: args.patientWarnedAboutAutoRelease, source: args.source, createdAt: now, updatedAt: now,
    })
    const bookingPublicId = publicId("bkg", bookingId)
    await ctx.db.patch(bookingId, { publicId: bookingPublicId })
    const booking = (await ctx.db.get(bookingId))!
    for (const participant of participants) await ctx.db.insert("bookingParticipants", { organizationId: organization._id, bookingId, personId: participant!._id, role: participant!._id === booker._id ? "booker" : "attendee", status: "registered", createdAt: now, updatedAt: now })
    for (const resourceId of offer.resourceIds) await ctx.db.insert("bookingAllocations", { organizationId: organization._id, bookingId, resourceId, localDate: offer.localDate, startsAt: offer.startsAt - service.bufferBeforeMinutes * 60_000, endsAt: offer.endsAt + service.bufferAfterMinutes * 60_000, status: "held", createdAt: now, updatedAt: now })
    if (offer.sessionId) {
      const session = await ctx.db.get(offer.sessionId)
      if (session) await ctx.db.patch(session._id, { reservedCount: session.reservedCount + offer.capacityUnits, updatedAt: now })
    }
    await ctx.db.patch(offer._id, { consumedAt: now })
    await ctx.db.insert("idempotencyKeys", { organizationId: organization._id, principalId: principal._id, operation: "booking.create", key: args.idempotencyKey, requestHash: args.requestHash, resourceType: "booking", resourcePublicId: bookingPublicId, response: { bookingId: bookingPublicId }, expiresAt: now + 7 * 24 * 60 * 60_000, createdAt: now })
    await emitEvent(ctx, organization._id, booking, "booking.created", { principalId: principal._id, type: principal.type, label: principal.name })

    const policy = await ctx.db.query("notificationPolicies").withIndex("by_organization_service", (q) => q.eq("organizationId", organization._id).eq("serviceId", service._id)).unique()
      ?? await ctx.db.query("notificationPolicies").withIndex("by_organization_service", (q) => q.eq("organizationId", organization._id).eq("serviceId", undefined)).unique()
    if (policy) {
      const attempts = policy.attempts.map((attempt) => ({ ...attempt, scheduledFor: clampToContactWindow(offer.startsAt - attempt.offsetMinutes * 60_000, offer.timezone, attempt.channel === "voice" ? policy.callStartMinute : policy.messageStartMinute, attempt.channel === "voice" ? policy.callEndMinute : policy.messageEndMinute) })).filter((attempt) => attempt.scheduledFor > now)
      if (!attempts.length) attempts.push({ offsetMinutes: 0, channel: "whatsapp", purpose: "confirmation", scheduledFor: now + 60_000 })
      for (const attempt of attempts) await ctx.db.insert("notificationDeliveries", { publicId: publicId("ntf", `${bookingId}_${attempt.offsetMinutes}_${attempt.channel}`), organizationId: organization._id, bookingId, personId: booker._id, channel: attempt.channel, purpose: attempt.purpose, provider: attempt.channel === "voice" ? "livekit_pbx" : "n8n", scheduledFor: attempt.scheduledFor, status: "queued", attempt: 0, createdAt: now, updatedAt: now })
    }
    return { bookingId: bookingPublicId, status: "pending_confirmation" as const, startsAt: new Date(offer.startsAt).toISOString(), endsAt: new Date(offer.endsAt).toISOString(), confirmationDeadlineAt: confirmationDeadlineAt ? new Date(confirmationDeadlineAt).toISOString() : undefined, idempotentReplay: false as const }
  },
})

export const transition = internalMutation({
  args: { principalId: v.id("principals"), organizationPublicId: v.string(), bookingPublicId: v.string(), action: v.union(v.literal("confirm"), v.literal("cancel_by_patient"), v.literal("cancel_by_business"), v.literal("complete"), v.literal("mark_no_show")), reason: v.optional(v.string()) },
  returns: v.object({ bookingId: v.string(), status: bookingStatus }),
  handler: async (ctx, args) => {
    const organization = await ctx.db.query("organizations").withIndex("by_public_id", (q) => q.eq("publicId", args.organizationPublicId)).unique()
    const booking = await ctx.db.query("bookings").withIndex("by_public_id", (q) => q.eq("publicId", args.bookingPublicId)).unique()
    if (!organization || !booking) fail("NOT_FOUND", "Organization or booking not found")
    if (booking.organizationId !== organization._id) fail("TENANT_SCOPE_VIOLATION", "Booking is outside the organization")
    const principal = await assertOrganizationPrincipal(ctx, organization._id, args.principalId)
    const next: Doc<"bookings">["status"] = args.action === "confirm" ? "confirmed" : args.action === "cancel_by_patient" ? "cancelled_by_patient" : args.action === "cancel_by_business" ? "cancelled_by_business" : args.action === "complete" ? "completed" : "no_show"
    const allowed = args.action === "confirm" ? booking.status === "pending_confirmation" : activeStatuses.has(booking.status)
    if (!allowed) fail("INVALID_STATE_TRANSITION", `Cannot ${args.action} a ${booking.status} booking`)
    const previous = booking.status
    const now = Date.now()
    await ctx.db.patch(booking._id, { status: next, updatedAt: now })
    if (next.startsWith("cancelled") || next === "completed" || next === "no_show") {
      const allocations = await ctx.db.query("bookingAllocations").withIndex("by_booking", (q) => q.eq("bookingId", booking._id)).collect()
      for (const allocation of allocations) await ctx.db.patch(allocation._id, { status: "released", updatedAt: now })
      if (booking.sessionId) {
        const session = await ctx.db.get(booking.sessionId)
        if (session) await ctx.db.patch(session._id, { reservedCount: Math.max(0, session.reservedCount - booking.capacityUnits), updatedAt: now })
      }
    }
    const updated = (await ctx.db.get(booking._id))!
    await emitEvent(ctx, organization._id, updated, `booking.${next}`, { principalId: principal._id, type: principal.type, label: principal.name }, previous, args.reason)
    return { bookingId: booking.publicId, status: next }
  },
})

export const reschedule = internalMutation({
  args: { principalId: v.id("principals"), organizationPublicId: v.string(), bookingPublicId: v.string(), offerId: v.string(), idempotencyKey: v.string(), requestHash: v.string(), reason: v.string() },
  returns: v.object({ bookingId: v.string(), previousBookingId: v.string(), status: v.literal("pending_confirmation"), idempotentReplay: v.boolean() }),
  handler: async (ctx, args) => {
    const organization = await ctx.db.query("organizations").withIndex("by_public_id", (q) => q.eq("publicId", args.organizationPublicId)).unique()
    const previous = await ctx.db.query("bookings").withIndex("by_public_id", (q) => q.eq("publicId", args.bookingPublicId)).unique()
    const offer = await ctx.db.query("availabilityOffers").withIndex("by_public_id", (q) => q.eq("publicId", args.offerId)).unique()
    if (!organization || !previous || !offer) fail("NOT_FOUND", "Organization, booking or offer not found")
    if (previous.organizationId !== organization._id || offer.organizationId !== organization._id) fail("TENANT_SCOPE_VIOLATION", "Reschedule context crosses organizations")
    if (!activeStatuses.has(previous.status)) fail("INVALID_STATE_TRANSITION", `Cannot reschedule a ${previous.status} booking`)
    if (offer.serviceId !== previous.serviceId || offer.capacityUnits !== previous.capacityUnits) fail("INVALID_INPUT", "Replacement offer must match service and participant capacity")
    const principal = await assertOrganizationPrincipal(ctx, organization._id, args.principalId)
    const replay = await ctx.db.query("idempotencyKeys").withIndex("by_scope_key", (q) => q.eq("organizationId", organization._id).eq("principalId", principal._id).eq("operation", "booking.reschedule").eq("key", args.idempotencyKey)).unique()
    if (replay) {
      if (replay.requestHash !== args.requestHash) fail("IDEMPOTENCY_CONFLICT", "Idempotency key was used with a different reschedule request")
      return { bookingId: replay.resourcePublicId, previousBookingId: previous.publicId, status: "pending_confirmation" as const, idempotentReplay: true }
    }
    const service = await ctx.db.get(previous.serviceId)
    if (!service) fail("NOT_FOUND", "Service not found")
    await ensureOfferAvailable(ctx, offer, service, previous._id)
    const now = Date.now()
    const location = offer.locationId ? await ctx.db.get(offer.locationId) : null
    const id = await ctx.db.insert("bookings", {
      publicId: "pending", organizationId: organization._id, serviceId: service._id, locationId: offer.locationId, sessionId: offer.sessionId,
      bookerPersonId: previous.bookerPersonId, status: "pending_confirmation", bookingMode: offer.bookingMode, modality: offer.snapshot.modality,
      startsAt: offer.startsAt, endsAt: offer.endsAt, localDate: offer.localDate, timezone: offer.timezone, shift: offer.shift, capacityUnits: offer.capacityUnits,
      snapshot: { serviceName: offer.snapshot.serviceName, durationMinutes: offer.snapshot.durationMinutes, bufferBeforeMinutes: service.bufferBeforeMinutes, bufferAfterMinutes: service.bufferAfterMinutes, locationName: location?.name, price: offer.snapshot.price },
      confirmationDeadlineAt: service.autoReleaseUnconfirmed && !service.neverAutoCancel ? Math.max(now + 60 * 60_000, offer.startsAt - 24 * 60 * 60_000) : undefined,
      patientWarnedAboutAutoRelease: previous.patientWarnedAboutAutoRelease, previousBookingId: previous._id, source: previous.source, createdAt: now, updatedAt: now,
    })
    const bookingPublicId = publicId("bkg", id)
    await ctx.db.patch(id, { publicId: bookingPublicId })
    const participants = await ctx.db.query("bookingParticipants").withIndex("by_booking", (q) => q.eq("bookingId", previous._id)).collect()
    for (const participant of participants.filter((item) => item.status === "registered")) await ctx.db.insert("bookingParticipants", { organizationId: organization._id, bookingId: id, personId: participant.personId, role: participant.role, coverageId: participant.coverageId, status: "registered", createdAt: now, updatedAt: now })
    for (const resourceId of offer.resourceIds) await ctx.db.insert("bookingAllocations", { organizationId: organization._id, bookingId: id, resourceId, localDate: offer.localDate, startsAt: offer.startsAt - service.bufferBeforeMinutes * 60_000, endsAt: offer.endsAt + service.bufferAfterMinutes * 60_000, status: "held", createdAt: now, updatedAt: now })
    const oldAllocations = await ctx.db.query("bookingAllocations").withIndex("by_booking", (q) => q.eq("bookingId", previous._id)).collect()
    for (const allocation of oldAllocations) await ctx.db.patch(allocation._id, { status: "released", updatedAt: now })
    await ctx.db.patch(previous._id, { status: "rescheduled", updatedAt: now })
    await ctx.db.patch(offer._id, { consumedAt: now })
    if (previous.sessionId) {
      const oldSession = await ctx.db.get(previous.sessionId)
      if (oldSession) await ctx.db.patch(oldSession._id, { reservedCount: Math.max(0, oldSession.reservedCount - previous.capacityUnits), updatedAt: now })
    }
    if (offer.sessionId) {
      const newSession = await ctx.db.get(offer.sessionId)
      if (newSession) await ctx.db.patch(newSession._id, { reservedCount: newSession.reservedCount + offer.capacityUnits, updatedAt: now })
    }
    await ctx.db.insert("idempotencyKeys", { organizationId: organization._id, principalId: principal._id, operation: "booking.reschedule", key: args.idempotencyKey, requestHash: args.requestHash, resourceType: "booking", resourcePublicId: bookingPublicId, response: { bookingId: bookingPublicId, previousBookingId: previous.publicId }, expiresAt: now + 7 * 24 * 60 * 60_000, createdAt: now })
    const created = (await ctx.db.get(id))!
    await emitEvent(ctx, organization._id, created, "booking.rescheduled_to", { principalId: principal._id, type: principal.type, label: principal.name }, undefined, args.reason)
    const updatedPrevious = (await ctx.db.get(previous._id))!
    await emitEvent(ctx, organization._id, updatedPrevious, "booking.rescheduled_from", { principalId: principal._id, type: principal.type, label: principal.name }, previous.status, args.reason)
    return { bookingId: bookingPublicId, previousBookingId: previous.publicId, status: "pending_confirmation" as const, idempotentReplay: false }
  },
})

export const listUpcoming = query({
  args: { organizationPublicId: v.string(), limit: v.optional(v.number()) },
  returns: v.array(v.object({ bookingId: v.string(), serviceName: v.string(), status: bookingStatus, startsAt: v.string(), localDate: v.string(), timezone: v.string(), participantCount: v.number(), mode: v.string() })),
  handler: async (ctx, args) => {
    if (!(await ctx.auth.getUserIdentity())) return []
    const organization = await ctx.db.query("organizations").withIndex("by_public_id", (q) => q.eq("publicId", args.organizationPublicId)).unique()
    if (!organization) return []
    const bookings = await ctx.db.query("bookings").withIndex("by_organization_start", (q) => q.eq("organizationId", organization._id).gte("startsAt", Date.now())).take(Math.min(args.limit ?? 30, 100))
    return bookings.map((item) => ({ bookingId: item.publicId, serviceName: item.snapshot.serviceName, status: item.status, startsAt: new Date(item.startsAt).toISOString(), localDate: item.localDate, timezone: item.timezone, participantCount: item.capacityUnits, mode: item.bookingMode }))
  },
})

export const autoReleaseDue = internalMutation({
  args: {},
  returns: v.object({ released: v.number() }),
  handler: async (ctx) => {
    const due = await ctx.db.query("bookings").withIndex("by_status_deadline", (q) => q.eq("status", "pending_confirmation").lte("confirmationDeadlineAt", Date.now())).take(100)
    let released = 0
    for (const booking of due) {
      const service = await ctx.db.get(booking.serviceId)
      if (!service?.autoReleaseUnconfirmed || service.neverAutoCancel || !booking.patientWarnedAboutAutoRelease) continue
      const deliveries = await ctx.db.query("notificationDeliveries").withIndex("by_booking", (q) => q.eq("bookingId", booking._id)).collect()
      if (!canAutoRelease({ autoReleaseUnconfirmed: service.autoReleaseUnconfirmed, neverAutoCancel: service.neverAutoCancel, warned: booking.patientWarnedAboutAutoRelease, alternateChannelRequired: true, deliveries })) continue
      const now = Date.now()
      await ctx.db.patch(booking._id, { status: "cancelled_unconfirmed", updatedAt: now })
      const allocations = await ctx.db.query("bookingAllocations").withIndex("by_booking", (q) => q.eq("bookingId", booking._id)).collect()
      for (const allocation of allocations) await ctx.db.patch(allocation._id, { status: "released", updatedAt: now })
      const updated = (await ctx.db.get(booking._id))!
      await emitEvent(ctx, booking.organizationId, updated, "booking.cancelled_unconfirmed", { type: "platform", label: "confirmation policy" }, "pending_confirmation", "Confirmation deadline elapsed after delivered and alternate-channel attempts")
      released += 1
    }
    return { released }
  },
})
