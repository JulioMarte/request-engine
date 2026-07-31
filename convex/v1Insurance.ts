import { v } from "convex/values"
import { internalMutation } from "./_generated/server"
import { fail } from "./lib/errors"
import { publicId } from "./lib/ids"

export const createPayer = internalMutation({
  args: { principalId: v.id("principals"), countryCode: v.string(), name: v.string(), shortName: v.string() },
  returns: v.object({ payerId: v.string() }),
  handler: async (ctx, args) => {
    const principal = await ctx.db.get(args.principalId)
    if (!principal || principal.type !== "platform") fail("INSUFFICIENT_SCOPE", "Only the platform can manage the payer directory")
    const now = Date.now()
    const id = await ctx.db.insert("payers", { publicId: "pending", countryCode: args.countryCode, name: args.name, shortName: args.shortName, status: "active", createdAt: now, updatedAt: now })
    const payerId = publicId("pay", id)
    await ctx.db.patch(id, { publicId: payerId })
    return { payerId }
  },
})

export const createCoverage = internalMutation({
  args: { organizationPublicId: v.string(), personPublicId: v.string(), payerPublicId: v.string(), policyHolderPersonPublicId: v.optional(v.string()), memberNumberEncrypted: v.string(), memberNumberBlindHash: v.string(), memberNumberMasked: v.string(), encryptionKeyVersion: v.number(), validFrom: v.optional(v.string()), validThrough: v.optional(v.string()) },
  returns: v.object({ coverageId: v.string(), memberNumberMasked: v.string(), status: v.literal("unverified") }),
  handler: async (ctx, args) => {
    const organization = await ctx.db.query("organizations").withIndex("by_public_id", (q) => q.eq("publicId", args.organizationPublicId)).unique()
    const person = await ctx.db.query("people").withIndex("by_public_id", (q) => q.eq("publicId", args.personPublicId)).unique()
    const payer = await ctx.db.query("payers").withIndex("by_public_id", (q) => q.eq("publicId", args.payerPublicId)).unique()
    const holder = args.policyHolderPersonPublicId ? await ctx.db.query("people").withIndex("by_public_id", (q) => q.eq("publicId", args.policyHolderPersonPublicId!)).unique() : null
    if (!organization || !person || !payer) fail("NOT_FOUND", "Organization, person or payer not found")
    if (person.organizationId !== organization._id || (holder && holder.organizationId !== organization._id)) fail("TENANT_SCOPE_VIOLATION", "Coverage crosses organizations")
    const id = await ctx.db.insert("insuranceCoverages", { organizationId: organization._id, personId: person._id, payerId: payer._id, memberNumberEncrypted: args.memberNumberEncrypted, memberNumberBlindHash: args.memberNumberBlindHash, memberNumberMasked: args.memberNumberMasked, encryptionKeyVersion: args.encryptionKeyVersion, policyHolderPersonId: holder?._id, validFrom: args.validFrom, validThrough: args.validThrough, status: "unverified", createdAt: Date.now(), updatedAt: Date.now() })
    return { coverageId: id, memberNumberMasked: args.memberNumberMasked, status: "unverified" as const }
  },
})

export const createProviderCredential = internalMutation({
  args: { organizationPublicId: v.string(), personPublicId: v.string(), type: v.union(v.literal("exequatur"), v.literal("professional_license"), v.literal("board_certification"), v.literal("other")), countryCode: v.string(), issuer: v.string(), valueEncrypted: v.string(), valueMasked: v.string(), blindHash: v.string(), encryptionKeyVersion: v.number(), validThrough: v.optional(v.string()) },
  returns: v.object({ credentialId: v.string(), valueMasked: v.string(), status: v.literal("unverified") }),
  handler: async (ctx, args) => {
    const organization = await ctx.db.query("organizations").withIndex("by_public_id", (q) => q.eq("publicId", args.organizationPublicId)).unique()
    const person = await ctx.db.query("people").withIndex("by_public_id", (q) => q.eq("publicId", args.personPublicId)).unique()
    if (!organization || !person) fail("NOT_FOUND", "Organization or professional not found")
    if (person.organizationId !== organization._id) fail("TENANT_SCOPE_VIOLATION", "Professional is outside the organization")
    const id = await ctx.db.insert("providerCredentials", { organizationId: organization._id, personId: person._id, type: args.type, countryCode: args.countryCode, issuer: args.issuer, valueEncrypted: args.valueEncrypted, valueMasked: args.valueMasked, blindHash: args.blindHash, encryptionKeyVersion: args.encryptionKeyVersion, validThrough: args.validThrough, status: "unverified", createdAt: Date.now(), updatedAt: Date.now() })
    return { credentialId: id, valueMasked: args.valueMasked, status: "unverified" as const }
  },
})

