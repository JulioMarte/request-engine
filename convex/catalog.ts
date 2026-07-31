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
  returns: v.array(v.object({ _id: v.id("catalogItems"), _creationTime: v.number(), tenantId: v.id("tenants"), name: v.string(), description: v.string(), type: catalogType, synonyms: v.array(v.string()), fulfillmentType, basePrice: v.optional(v.number()), durationMinutes: v.optional(v.number()), isActive: v.boolean(), metadata: v.optional(v.record(v.string(), v.union(v.string(), v.number(), v.boolean(), v.null()))), currency: v.optional(v.string()), sku: v.optional(v.string()), source: v.optional(v.string()), taxRate: v.optional(v.number()), unit: v.optional(v.string()), createdAt: v.number(), updatedAt: v.number() })),
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
  returns: v.id("catalogItems"),
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
  returns: v.id("catalogItems"),
  handler: async (ctx, args) => {
    const { catalogItemId, ...patch } = args
    await ctx.db.patch(catalogItemId, { ...patch, updatedAt: Date.now() })
    return catalogItemId
  },
})
