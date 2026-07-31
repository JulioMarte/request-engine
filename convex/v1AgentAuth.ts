import { v } from "convex/values"
import { internalMutation, internalQuery } from "./_generated/server"
import { principalType } from "./domainValidators"
import { fail } from "./lib/errors"

export const resolve = internalQuery({
  args: { secretHash: v.string() },
  returns: v.union(v.null(), v.object({ keyId: v.id("apiKeys"), principalId: v.id("principals"), principalType, principalName: v.string(), organizationId: v.optional(v.id("organizations")), organizationPublicId: v.optional(v.string()), scopes: v.array(v.string()) })),
  handler: async (ctx, args) => {
    const key = await ctx.db.query("apiKeys").withIndex("by_hash", (q) => q.eq("secretHash", args.secretHash)).unique()
    if (!key || key.revokedAt || (key.expiresAt && key.expiresAt <= Date.now())) return null
    const principal = await ctx.db.get(key.principalId)
    if (!principal || principal.status !== "active") return null
    const organization = principal.organizationId ? await ctx.db.get(principal.organizationId) : null
    return { keyId: key._id, principalId: principal._id, principalType: principal.type, principalName: principal.name, organizationId: principal.organizationId, organizationPublicId: organization?.publicId, scopes: key.scopes }
  },
})

export const store = internalMutation({
  args: { principalPublicId: v.string(), prefix: v.string(), secretHash: v.string(), scopes: v.array(v.string()), expiresAt: v.optional(v.number()) },
  returns: v.object({ keyId: v.string(), prefix: v.string() }),
  handler: async (ctx, args) => {
    const principal = await ctx.db.query("principals").withIndex("by_public_id", (q) => q.eq("publicId", args.principalPublicId)).unique()
    if (!principal) fail("NOT_FOUND", "Principal not found")
    const id = await ctx.db.insert("apiKeys", { principalId: principal._id, organizationId: principal.organizationId, prefix: args.prefix, secretHash: args.secretHash, scopes: args.scopes, expiresAt: args.expiresAt, createdAt: Date.now() })
    return { keyId: id, prefix: args.prefix }
  },
})

export const touch = internalMutation({
  args: { keyId: v.id("apiKeys") },
  returns: v.null(),
  handler: async (ctx, args) => {
    const key = await ctx.db.get(args.keyId)
    if (key) await ctx.db.patch(key._id, { lastUsedAt: Date.now() })
    return null
  },
})

export const revoke = internalMutation({
  args: { keyId: v.id("apiKeys"), principalId: v.id("principals") },
  returns: v.null(),
  handler: async (ctx, args) => {
    const key = await ctx.db.get(args.keyId)
    if (!key || key.principalId !== args.principalId) fail("TENANT_SCOPE_VIOLATION", "API key is outside the principal")
    await ctx.db.patch(key._id, { revokedAt: Date.now() })
    return null
  },
})

