import { v } from "convex/values"
import { mutation, query } from "./_generated/server"

const catalogType = v.union(
  v.literal("service"),
  v.literal("product"),
  v.literal("package"),
  v.literal("asset"),
  v.literal("custom"),
)

const fulfillmentType = v.union(
  v.literal("information"),
  v.literal("appointment"),
  v.literal("quote"),
  v.literal("handoff"),
)

export const listByTenant = query({
  args: { tenantId: v.id("tenants") },
  handler: async (ctx, args) => {
    return ctx.db
      .query("catalogItems")
      .withIndex("by_tenant", (q) => q.eq("tenantId", args.tenantId))
      .collect()
  },
})

export const create = mutation({
  args: {
    tenantId: v.id("tenants"),
    name: v.string(),
    description: v.string(),
    type: catalogType,
    fulfillmentType,
    synonyms: v.optional(v.array(v.string())),
    basePrice: v.optional(v.number()),
    durationMinutes: v.optional(v.number()),
  },
  handler: async (ctx, args) => {
    const now = Date.now()
    return ctx.db.insert("catalogItems", {
      ...args,
      synonyms: args.synonyms ?? [],
      isActive: true,
      createdAt: now,
      updatedAt: now,
    })
  },
})

export const update = mutation({
  args: {
    catalogItemId: v.id("catalogItems"),
    name: v.optional(v.string()),
    description: v.optional(v.string()),
    isActive: v.optional(v.boolean()),
  },
  handler: async (ctx, args) => {
    const { catalogItemId, ...patch } = args
    await ctx.db.patch(catalogItemId, { ...patch, updatedAt: Date.now() })
    return catalogItemId
  },
})
