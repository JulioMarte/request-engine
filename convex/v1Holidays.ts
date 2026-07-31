import { v } from "convex/values"
import { internalMutation } from "./_generated/server"
import { fail } from "./lib/errors"
import { publicId } from "./lib/ids"
import { addLocalDays, localDateAndMinute } from "./lib/time"

const approvedSources = ["presidencia.gob.do", "mt.gob.do", "opm.gov"]

export const importOfficial = internalMutation({
  args: { principalId: v.id("principals"), countryCode: v.string(), subdivisionCode: v.optional(v.string()), sourceUrl: v.string(), fetchedAt: v.number(), occurrences: v.array(v.object({ localDate: v.string(), observedDate: v.optional(v.string()), name: v.string() })) },
  returns: v.object({ imported: v.number(), skipped: v.number() }),
  handler: async (ctx, args) => {
    const principal = await ctx.db.get(args.principalId)
    if (!principal || principal.type !== "platform") fail("INSUFFICIENT_SCOPE", "Only the platform principal can import official holidays")
    const hostname = new URL(args.sourceUrl).hostname.replace(/^www\./, "")
    if (!approvedSources.some((domain) => hostname === domain || hostname.endsWith(`.${domain}`))) fail("INVALID_INPUT", "Holiday source is not on the official allowlist")
    let imported = 0
    let skipped = 0
    for (const occurrence of args.occurrences) {
      const existing = await ctx.db.query("holidayOccurrences").withIndex("by_country_date", (q) => q.eq("countryCode", args.countryCode).eq("localDate", occurrence.localDate)).collect()
      if (existing.some((item) => item.subdivisionCode === args.subdivisionCode && item.name === occurrence.name)) {
        skipped += 1
        continue
      }
      const now = Date.now()
      const id = await ctx.db.insert("holidayOccurrences", { publicId: "pending", countryCode: args.countryCode, subdivisionCode: args.subdivisionCode, localDate: occurrence.localDate, observedDate: occurrence.observedDate, name: occurrence.name, sourceUrl: args.sourceUrl, fetchedAt: args.fetchedAt, reviewStatus: "pending", createdAt: now, updatedAt: now })
      await ctx.db.patch(id, { publicId: publicId("hol", id) })
      imported += 1
    }
    return { imported, skipped }
  },
})

export const reviewSource = internalMutation({
  args: { principalId: v.id("principals"), holidayPublicId: v.string(), accepted: v.boolean() },
  returns: v.null(),
  handler: async (ctx, args) => {
    const principal = await ctx.db.get(args.principalId)
    if (!principal || principal.type !== "platform") fail("INSUFFICIENT_SCOPE", "Only the platform principal can review imported holidays")
    const holiday = await ctx.db.query("holidayOccurrences").withIndex("by_public_id", (q) => q.eq("publicId", args.holidayPublicId)).unique()
    if (!holiday) fail("NOT_FOUND", "Holiday not found")
    await ctx.db.patch(holiday._id, { reviewStatus: args.accepted ? "confirmed" : "rejected", updatedAt: Date.now() })
    return null
  },
})

export const prepareSevenDayReviews = internalMutation({
  args: {},
  returns: v.object({ created: v.number() }),
  handler: async (ctx) => {
    const todayUtc = localDateAndMinute(Date.now(), "UTC").localDate
    const targetDates = Array.from({ length: 3 }, (_, offset) => addLocalDays(todayUtc, 6 + offset))
    let created = 0
    for (const countryCode of ["DO", "US"]) {
      for (const targetDate of targetDates) {
        const holidays = await ctx.db.query("holidayOccurrences").withIndex("by_country_date", (q) => q.eq("countryCode", countryCode).eq("localDate", targetDate)).collect()
        for (const holiday of holidays.filter((item) => item.reviewStatus === "confirmed")) {
          const locations = await ctx.db.query("locations").filter((q) => q.eq(q.field("countryCode"), countryCode)).collect()
          for (const location of locations.filter((item) => !holiday.subdivisionCode || item.subdivisionCode === holiday.subdivisionCode)) {
            const existing = await ctx.db.query("holidayReviews").withIndex("by_location_holiday", (q) => q.eq("locationId", location._id).eq("holidayId", holiday._id)).unique()
            if (existing) continue
            const now = Date.now()
            await ctx.db.insert("holidayReviews", { organizationId: location.organizationId, locationId: location._id, holidayId: holiday._id, decision: "pending", windows: [], createdAt: now, updatedAt: now })
            await ctx.db.insert("outboxEvents", { eventId: publicId("evt", `${location._id}_${holiday._id}`), eventType: "holiday.opening_confirmation_requested", version: 1, organizationId: location.organizationId, aggregateType: "holiday_review", aggregatePublicId: publicId("hol", holiday._id), payload: { holidayName: holiday.name, localDate: holiday.localDate, locationId: location.publicId }, status: "pending", attempts: 0, availableAt: now, occurredAt: now, updatedAt: now })
            created += 1
          }
        }
      }
    }
    return { created }
  },
})

export const decideOpening = internalMutation({
  args: { principalId: v.id("principals"), organizationPublicId: v.string(), locationPublicId: v.string(), holidayPublicId: v.string(), decision: v.union(v.literal("open"), v.literal("closed"), v.literal("custom_hours")), windows: v.array(v.object({ startMinute: v.number(), endMinute: v.number() })) },
  returns: v.object({ affectedBookings: v.number(), decision: v.string() }),
  handler: async (ctx, args) => {
    const organization = await ctx.db.query("organizations").withIndex("by_public_id", (q) => q.eq("publicId", args.organizationPublicId)).unique()
    const location = await ctx.db.query("locations").withIndex("by_public_id", (q) => q.eq("publicId", args.locationPublicId)).unique()
    const principal = await ctx.db.get(args.principalId)
    const holiday = await ctx.db.query("holidayOccurrences").withIndex("by_public_id", (q) => q.eq("publicId", args.holidayPublicId)).unique()
    if (!organization || !location || !principal || !holiday) fail("NOT_FOUND", "Holiday review context not found")
    if (location.organizationId !== organization._id || (principal.type !== "platform" && principal.organizationId !== organization._id)) fail("TENANT_SCOPE_VIOLATION", "Holiday review crosses organizations")
    const review = await ctx.db.query("holidayReviews").withIndex("by_location_holiday", (q) => q.eq("locationId", location._id).eq("holidayId", holiday._id)).unique()
    if (!review) fail("NOT_FOUND", "Holiday review was not prepared")
    const now = Date.now()
    await ctx.db.patch(review._id, { decision: args.decision, windows: args.windows, decidedBy: principal._id, decidedAt: now, updatedAt: now })
    const bookings = await ctx.db.query("bookings").withIndex("by_organization_start", (q) => q.eq("organizationId", organization._id)).collect()
    const affected = bookings.filter((booking) => booking.locationId === location._id && booking.localDate === holiday.localDate && !booking.status.startsWith("cancelled") && booking.status !== "rescheduled")
    await ctx.db.insert("outboxEvents", { eventId: publicId("evt", `${review._id}_${now}`), eventType: "holiday.opening_decided", version: 1, organizationId: organization._id, aggregateType: "holiday_review", aggregatePublicId: publicId("hol", holiday._id), payload: { decision: args.decision, affectedBookings: affected.length, localDate: holiday.localDate, locationId: location.publicId }, status: "pending", attempts: 0, availableAt: now, occurredAt: now, updatedAt: now })
    return { affectedBookings: affected.length, decision: args.decision }
  },
})
