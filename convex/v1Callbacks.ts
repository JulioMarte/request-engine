import { v } from "convex/values"
import { internalMutation } from "./_generated/server"
import { channel } from "./domainValidators"
import { fail } from "./lib/errors"

export const notification = internalMutation({
  args: {
    provider: v.string(), externalEventId: v.string(), organizationPublicId: v.string(), deliveryPublicId: v.string(),
    status: v.union(v.literal("dispatched"), v.literal("delivered"), v.literal("failed"), v.literal("responded")),
    channel, resultCode: v.optional(v.string()), sipStatus: v.optional(v.string()),
    intent: v.optional(v.union(v.literal("confirm"), v.literal("cancel"), v.literal("reprogram"), v.literal("unknown"))), payloadHash: v.string(),
  },
  returns: v.object({ accepted: v.boolean(), duplicate: v.boolean(), intentApplied: v.boolean() }),
  handler: async (ctx, args) => {
    const duplicate = await ctx.db.query("webhookReceipts").withIndex("by_provider_event", (q) => q.eq("provider", args.provider).eq("externalEventId", args.externalEventId)).unique()
    if (duplicate) return { accepted: true, duplicate: true, intentApplied: false }
    const organization = await ctx.db.query("organizations").withIndex("by_public_id", (q) => q.eq("publicId", args.organizationPublicId)).unique()
    const delivery = await ctx.db.query("notificationDeliveries").withIndex("by_public_id", (q) => q.eq("publicId", args.deliveryPublicId)).unique()
    if (!organization || !delivery) fail("NOT_FOUND", "Organization or notification delivery not found")
    if (delivery.organizationId !== organization._id || delivery.channel !== args.channel) fail("TENANT_SCOPE_VIOLATION", "Callback does not match the delivery")
    const now = Date.now()
    await ctx.db.insert("webhookReceipts", { provider: args.provider, externalEventId: args.externalEventId, eventType: "notification.callback", organizationId: organization._id, payloadHash: args.payloadHash, status: "accepted", receivedAt: now, processedAt: now })
    await ctx.db.patch(delivery._id, { status: args.status, resultCode: args.resultCode ?? args.sipStatus, deliveredAt: args.status === "delivered" || args.status === "responded" ? now : undefined, updatedAt: now })
    let intentApplied = false
    if (delivery.bookingId && args.status === "responded" && (args.intent === "confirm" || args.intent === "cancel")) {
      const booking = await ctx.db.get(delivery.bookingId)
      if (booking?.status === "pending_confirmation") {
        const next = args.intent === "confirm" ? "confirmed" : "cancelled_by_patient"
        await ctx.db.patch(booking._id, { status: next, updatedAt: now })
        if (next === "cancelled_by_patient") {
          const allocations = await ctx.db.query("bookingAllocations").withIndex("by_booking", (q) => q.eq("bookingId", booking._id)).collect()
          for (const allocation of allocations) await ctx.db.patch(allocation._id, { status: "released", updatedAt: now })
        }
        await ctx.db.insert("bookingEvents", { organizationId: organization._id, bookingId: booking._id, eventType: `booking.${next}`, fromStatus: "pending_confirmation", toStatus: next, actor: { type: "integration", label: args.provider }, data: { deliveryId: delivery.publicId, structuredIntent: args.intent }, occurredAt: now })
        intentApplied = true
      }
    }
    return { accepted: true, duplicate: false, intentApplied }
  },
})

