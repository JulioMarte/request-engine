import { v } from "convex/values"
import { internalMutation, query } from "./_generated/server"
import { shift } from "./domainValidators"
import { fail } from "./lib/errors"
import { publicId } from "./lib/ids"

export const checkIn = internalMutation({
  args: { principalId: v.id("principals"), organizationPublicId: v.string(), bookingPublicId: v.optional(v.string()), servicePublicId: v.string(), locationPublicId: v.string(), personPublicId: v.string(), localDate: v.string(), shift, qrTokenHash: v.string() },
  returns: v.object({ queueEntryId: v.string(), ticketNumber: v.number(), peopleAhead: v.number(), estimatedWaitMinutes: v.number(), estimateIsGuaranteed: v.literal(false) }),
  handler: async (ctx, args) => {
    const organization = await ctx.db.query("organizations").withIndex("by_public_id", (q) => q.eq("publicId", args.organizationPublicId)).unique()
    const location = await ctx.db.query("locations").withIndex("by_public_id", (q) => q.eq("publicId", args.locationPublicId)).unique()
    const service = await ctx.db.query("services").withIndex("by_public_id", (q) => q.eq("publicId", args.servicePublicId)).unique()
    const person = await ctx.db.query("people").withIndex("by_public_id", (q) => q.eq("publicId", args.personPublicId)).unique()
    if (!organization || !location || !service || !person) fail("NOT_FOUND", "Queue context was not found")
    if ([location.organizationId, service.organizationId, person.organizationId].some((id) => id !== organization._id)) fail("TENANT_SCOPE_VIOLATION", "Queue context crosses organizations")
    const principal = await ctx.db.get(args.principalId)
    if (!principal || (principal.type !== "platform" && principal.organizationId !== organization._id)) fail("TENANT_SCOPE_VIOLATION", "Principal is outside the organization")
    if (service.bookingMode !== "arrival_window") fail("INVALID_INPUT", "Check-in tickets apply only to arrival-window services")
    const booking = args.bookingPublicId ? await ctx.db.query("bookings").withIndex("by_public_id", (q) => q.eq("publicId", args.bookingPublicId!)).unique() : null
    if (booking && (booking.organizationId !== organization._id || booking.serviceId !== service._id)) fail("TENANT_SCOPE_VIOLATION", "Booking does not match this queue")
    if (booking) {
      const existing = await ctx.db.query("queueEntries").withIndex("by_booking", (q) => q.eq("bookingId", booking._id)).unique()
      if (existing) {
        const ahead = await ctx.db.query("queueEntries").withIndex("by_queue_order", (q) => q.eq("locationId", location._id).eq("localDate", args.localDate).eq("shift", args.shift).eq("status", "waiting")).collect()
        return { queueEntryId: existing.publicId, ticketNumber: existing.ticketNumber, peopleAhead: ahead.filter((entry) => entry.priorityRank < existing.priorityRank || (entry.priorityRank === existing.priorityRank && entry.checkInSequence < existing.checkInSequence)).length, estimatedWaitMinutes: 0, estimateIsGuaranteed: false as const }
      }
    }
    const counter = await ctx.db.query("queueCounters").withIndex("by_window", (q) => q.eq("locationId", location._id).eq("localDate", args.localDate).eq("shift", args.shift)).unique()
    const ticketNumber = (counter?.lastTicketNumber ?? 0) + 1
    const sequence = (counter?.lastSequence ?? 0) + 1
    const now = Date.now()
    if (counter) await ctx.db.patch(counter._id, { lastTicketNumber: ticketNumber, lastSequence: sequence, updatedAt: now })
    else await ctx.db.insert("queueCounters", { locationId: location._id, localDate: args.localDate, shift: args.shift, lastTicketNumber: ticketNumber, lastSequence: sequence, updatedAt: now })
    const id = await ctx.db.insert("queueEntries", { publicId: "pending", organizationId: organization._id, bookingId: booking?._id, serviceId: service._id, locationId: location._id, localDate: args.localDate, shift: args.shift, personId: person._id, ticketNumber, checkInSequence: sequence, priorityRank: 100, qrTokenHash: args.qrTokenHash, qrTokenExpiresAt: now + 12 * 60 * 60_000, status: "waiting", checkedInAt: now, createdAt: now, updatedAt: now })
    const queueEntryId = publicId("que", id)
    await ctx.db.patch(id, { publicId: queueEntryId })
    if (booking) await ctx.db.patch(booking._id, { status: "checked_in", updatedAt: now })
    const ahead = await ctx.db.query("queueEntries").withIndex("by_queue_order", (q) => q.eq("locationId", location._id).eq("localDate", args.localDate).eq("shift", args.shift).eq("status", "waiting")).collect()
    const peopleAhead = Math.max(0, ahead.length - 1)
    return { queueEntryId, ticketNumber, peopleAhead, estimatedWaitMinutes: peopleAhead * service.durationMinutes, estimateIsGuaranteed: false as const }
  },
})

export const prioritize = internalMutation({
  args: { principalId: v.id("principals"), organizationPublicId: v.string(), queueEntryPublicId: v.string(), priorityRank: v.number(), reason: v.string() },
  returns: v.object({ queueEntryId: v.string(), priorityRank: v.number() }),
  handler: async (ctx, args) => {
    const organization = await ctx.db.query("organizations").withIndex("by_public_id", (q) => q.eq("publicId", args.organizationPublicId)).unique()
    const entry = await ctx.db.query("queueEntries").withIndex("by_public_id", (q) => q.eq("publicId", args.queueEntryPublicId)).unique()
    const principal = await ctx.db.get(args.principalId)
    if (!organization || !entry || !principal) fail("NOT_FOUND", "Organization, queue entry or principal not found")
    if (entry.organizationId !== organization._id || principal.organizationId !== organization._id) fail("TENANT_SCOPE_VIOLATION", "Queue priority crosses organizations")
    if (!args.reason.trim()) fail("MISSING_REQUIRED_FIELDS", "A reason is mandatory for priority changes")
    await ctx.db.patch(entry._id, { priorityRank: args.priorityRank, priorityReason: args.reason, prioritizedBy: principal._id, updatedAt: Date.now() })
    await ctx.db.insert("auditEvents", { publicId: publicId("aud", `${entry._id}_${Date.now()}`), organizationId: organization._id, actor: { principalId: principal._id, type: principal.type, label: principal.name }, action: "queue.priority_changed", targetType: "queue_entry", targetPublicId: entry.publicId, data: { priorityRank: args.priorityRank, reason: args.reason }, occurredAt: Date.now() })
    return { queueEntryId: entry.publicId, priorityRank: args.priorityRank }
  },
})

export const live = query({
  args: { organizationPublicId: v.string(), locationPublicId: v.string(), localDate: v.string(), shift },
  returns: v.array(v.object({ queueEntryId: v.string(), ticketNumber: v.number(), personName: v.string(), status: v.string(), peopleAhead: v.number(), estimatedWaitMinutes: v.number(), priorityReason: v.optional(v.string()) })),
  handler: async (ctx, args) => {
    if (!(await ctx.auth.getUserIdentity())) return []
    const organization = await ctx.db.query("organizations").withIndex("by_public_id", (q) => q.eq("publicId", args.organizationPublicId)).unique()
    const location = await ctx.db.query("locations").withIndex("by_public_id", (q) => q.eq("publicId", args.locationPublicId)).unique()
    if (!organization || !location || location.organizationId !== organization._id) return []
    const entries = await ctx.db.query("queueEntries").withIndex("by_queue_order", (q) => q.eq("locationId", location._id).eq("localDate", args.localDate).eq("shift", args.shift).eq("status", "waiting")).collect()
    entries.sort((a, b) => a.priorityRank - b.priorityRank || a.checkInSequence - b.checkInSequence)
    return Promise.all(entries.map(async (entry, index) => {
      const person = await ctx.db.get(entry.personId)
      const service = await ctx.db.get(entry.serviceId)
      return { queueEntryId: entry.publicId, ticketNumber: entry.ticketNumber, personName: person?.fullName ?? "Persona", status: entry.status, peopleAhead: index, estimatedWaitMinutes: index * (service?.durationMinutes ?? 15), priorityReason: entry.priorityReason }
    }))
  },
})
