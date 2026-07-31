import { v } from "convex/values"
import { internalMutation, query } from "./_generated/server"
import { fail } from "./lib/errors"
import { publicId } from "./lib/ids"

export const create = internalMutation({
  args: { organizationPublicId: v.string(), fullName: v.string(), dateOfBirth: v.optional(v.string()), preferredLocale: v.optional(v.string()), email: v.optional(v.string()), phoneE164: v.optional(v.string()) },
  returns: v.object({ personId: v.string(), fullName: v.string() }),
  handler: async (ctx, args) => {
    const organization = await ctx.db.query("organizations").withIndex("by_public_id", (q) => q.eq("publicId", args.organizationPublicId)).unique()
    if (!organization) fail("NOT_FOUND", "Organization not found")
    const now = Date.now()
    const id = await ctx.db.insert("people", { publicId: "pending", organizationId: organization._id, fullName: args.fullName, dateOfBirth: args.dateOfBirth, preferredLocale: args.preferredLocale, email: args.email, phoneE164: args.phoneE164, status: "active", createdAt: now, updatedAt: now })
    const personId = publicId("per", id)
    await ctx.db.patch(id, { publicId: personId })
    return { personId, fullName: args.fullName }
  },
})

export const storeIdentifier = internalMutation({
  args: { organizationPublicId: v.string(), personPublicId: v.string(), type: v.union(v.literal("national_id"), v.literal("passport"), v.literal("driver_license"), v.literal("other")), countryCode: v.string(), encryptedValue: v.string(), blindHash: v.string(), maskedValue: v.string(), encryptionKeyVersion: v.number() },
  returns: v.object({ identifierId: v.string(), maskedValue: v.string() }),
  handler: async (ctx, args) => {
    const organization = await ctx.db.query("organizations").withIndex("by_public_id", (q) => q.eq("publicId", args.organizationPublicId)).unique()
    const person = await ctx.db.query("people").withIndex("by_public_id", (q) => q.eq("publicId", args.personPublicId)).unique()
    if (!organization || !person) fail("NOT_FOUND", "Organization or person not found")
    if (person.organizationId !== organization._id) fail("TENANT_SCOPE_VIOLATION", "Person is outside the organization")
    const duplicate = await ctx.db.query("personIdentifiers").withIndex("by_organization_hash", (q) => q.eq("organizationId", organization._id).eq("blindHash", args.blindHash)).unique()
    if (duplicate && duplicate.personId !== person._id) fail("INVALID_INPUT", "Identifier is already assigned to another person")
    const id = await ctx.db.insert("personIdentifiers", { organizationId: organization._id, personId: person._id, type: args.type, countryCode: args.countryCode, encryptedValue: args.encryptedValue, blindHash: args.blindHash, maskedValue: args.maskedValue, encryptionKeyVersion: args.encryptionKeyVersion, createdAt: Date.now() })
    return { identifierId: id, maskedValue: args.maskedValue }
  },
})

export const relate = internalMutation({
  args: { organizationPublicId: v.string(), fromPersonPublicId: v.string(), toPersonPublicId: v.string(), type: v.union(v.literal("legal_guardian"), v.literal("parent"), v.literal("spouse"), v.literal("dependent"), v.literal("emergency_contact"), v.literal("other")), canBook: v.boolean() },
  returns: v.string(),
  handler: async (ctx, args) => {
    const organization = await ctx.db.query("organizations").withIndex("by_public_id", (q) => q.eq("publicId", args.organizationPublicId)).unique()
    const from = await ctx.db.query("people").withIndex("by_public_id", (q) => q.eq("publicId", args.fromPersonPublicId)).unique()
    const to = await ctx.db.query("people").withIndex("by_public_id", (q) => q.eq("publicId", args.toPersonPublicId)).unique()
    if (!organization || !from || !to) fail("NOT_FOUND", "Relationship parties not found")
    if (from.organizationId !== organization._id || to.organizationId !== organization._id) fail("TENANT_SCOPE_VIOLATION", "Relationship crosses organizations")
    return ctx.db.insert("personRelationships", { organizationId: organization._id, fromPersonId: from._id, toPersonId: to._id, type: args.type, canBook: args.canBook, createdAt: Date.now() })
  },
})

export const list = query({
  args: { organizationPublicId: v.string(), limit: v.optional(v.number()) },
  returns: v.array(v.object({ personId: v.string(), fullName: v.string(), email: v.optional(v.string()), phoneMasked: v.optional(v.string()), status: v.string() })),
  handler: async (ctx, args) => {
    if (!(await ctx.auth.getUserIdentity())) return []
    const organization = await ctx.db.query("organizations").withIndex("by_public_id", (q) => q.eq("publicId", args.organizationPublicId)).unique()
    if (!organization) return []
    const people = await ctx.db.query("people").filter((q) => q.eq(q.field("organizationId"), organization._id)).take(Math.min(args.limit ?? 50, 100))
    return people.map((person) => ({ personId: person.publicId, fullName: person.fullName, email: person.email, phoneMasked: person.phoneE164 ? `••••${person.phoneE164.slice(-4)}` : undefined, status: person.status }))
  },
})

