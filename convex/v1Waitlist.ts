import { v } from "convex/values"
import { internalMutation } from "./_generated/server"
import { modality, shift } from "./domainValidators"
import { fail } from "./lib/errors"
import { publicId } from "./lib/ids"

export const join = internalMutation({
  args: { principalId: v.id("principals"), organizationPublicId: v.string(), servicePublicId: v.string(), locationPublicId: v.optional(v.string()), personPublicId: v.string(), preferredDates: v.array(v.string()), preferredShifts: v.array(shift), modality: v.optional(modality), warnedAutoRelease: v.boolean() },
  returns: v.object({ waitlistEntryId: v.string(), status: v.literal("waiting") }),
  handler: async (ctx, args) => {
    const organization = await ctx.db.query("organizations").withIndex("by_public_id", (q) => q.eq("publicId", args.organizationPublicId)).unique()
    const service = await ctx.db.query("services").withIndex("by_public_id", (q) => q.eq("publicId", args.servicePublicId)).unique()
    const person = await ctx.db.query("people").withIndex("by_public_id", (q) => q.eq("publicId", args.personPublicId)).unique()
    const location = args.locationPublicId ? await ctx.db.query("locations").withIndex("by_public_id", (q) => q.eq("publicId", args.locationPublicId!)).unique() : null
    const principal = await ctx.db.get(args.principalId)
    if (!organization || !service || !person || !principal) fail("NOT_FOUND", "Waitlist context not found")
    if (service.organizationId !== organization._id || person.organizationId !== organization._id || (location && location.organizationId !== organization._id) || (principal.type !== "platform" && principal.organizationId !== organization._id)) fail("TENANT_SCOPE_VIOLATION", "Waitlist context crosses organizations")
    if (!service.waitlistEnabled) fail("INVALID_STATE_TRANSITION", "Waitlist is disabled for this service")
    const existing = await ctx.db.query("waitlistEntries").withIndex("by_person_service_status", (q) => q.eq("personId", person._id).eq("serviceId", service._id).eq("status", "waiting")).unique()
    if (existing) return { waitlistEntryId: existing.publicId, status: "waiting" as const }
    const now = Date.now()
    const id = await ctx.db.insert("waitlistEntries", { publicId: "pending", organizationId: organization._id, serviceId: service._id, locationId: location?._id, personId: person._id, preferredDates: args.preferredDates, preferredShifts: args.preferredShifts, modality: args.modality, warnedAutoRelease: args.warnedAutoRelease, status: "waiting", priority: now, createdAt: now, updatedAt: now })
    const waitlistEntryId = publicId("wle", id)
    await ctx.db.patch(id, { publicId: waitlistEntryId })
    return { waitlistEntryId, status: "waiting" as const }
  },
})

export const offerReleasedSpace = internalMutation({
  args: { principalId: v.id("principals"), organizationPublicId: v.string(), availabilityOfferPublicId: v.string() },
  returns: v.object({ strategy: v.union(v.literal("sequential"), v.literal("small_batch")), offered: v.number(), offerIds: v.array(v.string()) }),
  handler: async (ctx, args) => {
    const organization = await ctx.db.query("organizations").withIndex("by_public_id", (q) => q.eq("publicId", args.organizationPublicId)).unique()
    const availability = await ctx.db.query("availabilityOffers").withIndex("by_public_id", (q) => q.eq("publicId", args.availabilityOfferPublicId)).unique()
    const principal = await ctx.db.get(args.principalId)
    if (!organization || !availability || !principal) fail("NOT_FOUND", "Waitlist offer context not found")
    if (availability.organizationId !== organization._id || (principal.type !== "platform" && principal.organizationId !== organization._id)) fail("TENANT_SCOPE_VIOLATION", "Waitlist offer crosses organizations")
    if (availability.consumedAt || availability.expiresAt <= Date.now()) fail("OFFER_EXPIRED", "Availability offer is no longer valid")
    const strategy: "sequential" | "small_batch" = availability.startsAt - Date.now() > 6 * 60 * 60_000 ? "sequential" : "small_batch"
    const waiting = await ctx.db.query("waitlistEntries").withIndex("by_service_status", (q) => q.eq("serviceId", availability.serviceId).eq("status", "waiting")).collect()
    const eligible = waiting.filter((entry) => (!entry.locationId || entry.locationId === availability.locationId) && (!entry.preferredDates.length || entry.preferredDates.includes(availability.localDate)) && (!entry.preferredShifts.length || (availability.shift && entry.preferredShifts.includes(availability.shift)))).sort((a, b) => a.priority - b.priority).slice(0, strategy === "sequential" ? 1 : 3)
    const now = Date.now()
    const expiresAt = Math.min(availability.expiresAt, now + (strategy === "sequential" ? 60 : 15) * 60_000)
    const offerIds: string[] = []
    for (const entry of eligible) {
      const id = await ctx.db.insert("waitlistOffers", { publicId: "pending", organizationId: organization._id, entryId: entry._id, availabilityOfferId: availability._id, strategy, status: "pending", expiresAt, createdAt: now, updatedAt: now })
      const offerId = publicId("wlo", id)
      await ctx.db.patch(id, { publicId: offerId })
      await ctx.db.patch(entry._id, { status: "offered", updatedAt: now })
      offerIds.push(offerId)
    }
    return { strategy, offered: offerIds.length, offerIds }
  },
})

export const accept = internalMutation({
  args: { principalId: v.id("principals"), organizationPublicId: v.string(), waitlistOfferPublicId: v.string() },
  returns: v.object({ bookingId: v.string(), won: v.boolean() }),
  handler: async (ctx, args) => {
    const organization = await ctx.db.query("organizations").withIndex("by_public_id", (q) => q.eq("publicId", args.organizationPublicId)).unique()
    const waitlistOffer = await ctx.db.query("waitlistOffers").withIndex("by_public_id", (q) => q.eq("publicId", args.waitlistOfferPublicId)).unique()
    const principal = await ctx.db.get(args.principalId)
    if (!organization || !waitlistOffer || !principal) fail("NOT_FOUND", "Waitlist acceptance context not found")
    if (waitlistOffer.organizationId !== organization._id || (principal.type !== "platform" && principal.organizationId !== organization._id)) fail("TENANT_SCOPE_VIOLATION", "Waitlist acceptance crosses organizations")
    if (waitlistOffer.status !== "pending" || waitlistOffer.expiresAt <= Date.now()) return { bookingId: "", won: false }
    const availability = await ctx.db.get(waitlistOffer.availabilityOfferId)
    const entry = await ctx.db.get(waitlistOffer.entryId)
    if (!availability || !entry || availability.consumedAt || availability.expiresAt <= Date.now()) return { bookingId: "", won: false }
    const service = await ctx.db.get(availability.serviceId)
    const person = await ctx.db.get(entry.personId)
    if (!service || !person) fail("NOT_FOUND", "Service or person no longer exists")
    for (const resourceId of availability.resourceIds) {
      const allocations = await ctx.db.query("bookingAllocations").withIndex("by_resource_date_start", (q) => q.eq("resourceId", resourceId).eq("localDate", availability.localDate)).collect()
      if (allocations.some((allocation) => allocation.status === "held" && allocation.startsAt < availability.endsAt && allocation.endsAt > availability.startsAt)) return { bookingId: "", won: false }
    }
    const now = Date.now()
    const location = availability.locationId ? await ctx.db.get(availability.locationId) : null
    const id = await ctx.db.insert("bookings", { publicId: "pending", organizationId: organization._id, serviceId: service._id, locationId: availability.locationId, sessionId: availability.sessionId, bookerPersonId: person._id, status: "pending_confirmation", bookingMode: availability.bookingMode, modality: availability.snapshot.modality, startsAt: availability.startsAt, endsAt: availability.endsAt, localDate: availability.localDate, timezone: availability.timezone, shift: availability.shift, capacityUnits: 1, snapshot: { serviceName: service.name, durationMinutes: service.durationMinutes, bufferBeforeMinutes: service.bufferBeforeMinutes, bufferAfterMinutes: service.bufferAfterMinutes, locationName: location?.name, price: availability.snapshot.price }, confirmationDeadlineAt: service.autoReleaseUnconfirmed && !service.neverAutoCancel ? Math.max(now + 60 * 60_000, availability.startsAt - 24 * 60 * 60_000) : undefined, patientWarnedAboutAutoRelease: entry.warnedAutoRelease, source: "agent", createdAt: now, updatedAt: now })
    const bookingId = publicId("bkg", id)
    await ctx.db.patch(id, { publicId: bookingId })
    await ctx.db.insert("bookingParticipants", { organizationId: organization._id, bookingId: id, personId: person._id, role: "booker", status: "registered", createdAt: now, updatedAt: now })
    for (const resourceId of availability.resourceIds) await ctx.db.insert("bookingAllocations", { organizationId: organization._id, bookingId: id, resourceId, localDate: availability.localDate, startsAt: availability.startsAt - service.bufferBeforeMinutes * 60_000, endsAt: availability.endsAt + service.bufferAfterMinutes * 60_000, status: "held", createdAt: now, updatedAt: now })
    await ctx.db.patch(availability._id, { consumedAt: now })
    await ctx.db.patch(waitlistOffer._id, { status: "accepted", acceptedAt: now, updatedAt: now })
    await ctx.db.patch(entry._id, { status: "booked", updatedAt: now })
    const competing = await ctx.db.query("waitlistOffers").withIndex("by_availability_status", (q) => q.eq("availabilityOfferId", availability._id).eq("status", "pending")).collect()
    for (const other of competing) {
      await ctx.db.patch(other._id, { status: "lost", updatedAt: now })
      const otherEntry = await ctx.db.get(other.entryId)
      if (otherEntry) await ctx.db.patch(otherEntry._id, { status: "waiting", updatedAt: now })
    }
    await ctx.db.insert("bookingEvents", { organizationId: organization._id, bookingId: id, eventType: "booking.created_from_waitlist", toStatus: "pending_confirmation", actor: { principalId: principal._id, type: principal.type, label: principal.name }, data: { waitlistOfferId: waitlistOffer.publicId }, occurredAt: now })
    return { bookingId, won: true }
  },
})
