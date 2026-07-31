import { v } from "convex/values"
import { internalMutation, internalQuery, mutation, query } from "./_generated/server"
import { organizationStatus } from "./domainValidators"
import { fail } from "./lib/errors"
import { publicId } from "./lib/ids"

const organizationSummary = v.object({
  id: v.string(),
  name: v.string(),
  industry: v.string(),
  timezone: v.string(),
  countryCode: v.string(),
  status: organizationStatus,
})

export const bootstrap = internalMutation({
  args: {
    name: v.string(),
    legalName: v.optional(v.string()),
    industry: v.string(),
    countryCode: v.string(),
    timezone: v.string(),
    locale: v.string(),
    locationName: v.string(),
    terminology: v.string(),
    ownerFullName: v.string(),
    ownerEmail: v.string(),
    ownerPhoneE164: v.string(),
  },
  returns: v.object({ organizationId: v.string(), locationId: v.string(), ownerId: v.string(), principalId: v.string() }),
  handler: async (ctx, args) => {
    const now = Date.now()
    const organizationId = await ctx.db.insert("organizations", {
      publicId: "pending",
      name: args.name,
      legalName: args.legalName,
      industry: args.industry,
      countryCode: args.countryCode,
      timezone: args.timezone,
      locale: args.locale,
      status: "draft",
      holidayMentionEnabled: false,
      createdAt: now,
      updatedAt: now,
    })
    const organizationPublicId = publicId("org", organizationId)
    await ctx.db.patch(organizationId, { publicId: organizationPublicId })

    const locationId = await ctx.db.insert("locations", {
      publicId: "pending",
      organizationId,
      name: args.locationName,
      terminology: args.terminology,
      timezone: args.timezone,
      countryCode: args.countryCode,
      status: "active",
      createdAt: now,
      updatedAt: now,
    })
    const locationPublicId = publicId("loc", locationId)
    await ctx.db.patch(locationId, { publicId: locationPublicId })

    const ownerId = await ctx.db.insert("people", {
      publicId: "pending",
      organizationId,
      fullName: args.ownerFullName,
      preferredLocale: args.locale,
      email: args.ownerEmail,
      phoneE164: args.ownerPhoneE164,
      status: "active",
      createdAt: now,
      updatedAt: now,
    })
    const ownerPublicId = publicId("per", ownerId)
    await ctx.db.patch(ownerId, { publicId: ownerPublicId })

    const principalId = await ctx.db.insert("principals", {
      publicId: "pending",
      organizationId,
      type: "human",
      name: args.ownerFullName,
      personId: ownerId,
      status: "active",
      createdAt: now,
      updatedAt: now,
    })
    const principalPublicId = publicId("prn", principalId)
    await ctx.db.patch(principalId, { publicId: principalPublicId })
    await ctx.db.insert("memberships", { organizationId, personId: ownerId, role: "owner", status: "active", createdAt: now, updatedAt: now })
    await ctx.db.insert("notificationPolicies", {
      organizationId,
      messageStartMinute: 9 * 60,
      messageEndMinute: 20 * 60,
      callStartMinute: 9 * 60,
      callEndMinute: 19 * 60,
      attempts: [
        { offsetMinutes: 72 * 60, channel: "whatsapp", purpose: "confirmation" },
        { offsetMinutes: 48 * 60, channel: "email", purpose: "confirmation" },
        { offsetMinutes: 30 * 60, channel: "voice", purpose: "confirmation" },
      ],
      autoReleaseAtMinutes: 24 * 60,
      alternateChannelRequired: true,
      createdAt: now,
      updatedAt: now,
    })
    await ctx.db.insert("onboardingSessions", {
      publicId: publicId("onb", organizationId),
      organizationId,
      ownerPersonId: ownerId,
      ownerPhoneE164: args.ownerPhoneE164,
      ownerEmail: args.ownerEmail,
      phoneAllowed: true,
      webhookVerified: true,
      state: "collecting_business_profile",
      completedSteps: ["organization_created"],
      createdAt: now,
      updatedAt: now,
    })
    return { organizationId: organizationPublicId, locationId: locationPublicId, ownerId: ownerPublicId, principalId: principalPublicId }
  },
})

export const getInternal = internalQuery({
  args: { publicId: v.string() },
  returns: v.union(v.null(), v.object({ id: v.id("organizations"), publicId: v.string(), name: v.string(), timezone: v.string(), locale: v.string(), countryCode: v.string(), status: organizationStatus })),
  handler: async (ctx, args) => {
    const item = await ctx.db.query("organizations").withIndex("by_public_id", (q) => q.eq("publicId", args.publicId)).unique()
    return item ? { id: item._id, publicId: item.publicId, name: item.name, timezone: item.timezone, locale: item.locale, countryCode: item.countryCode, status: item.status } : null
  },
})

export const list = query({
  args: {},
  returns: v.array(organizationSummary),
  handler: async (ctx) => {
    const identity = await ctx.auth.getUserIdentity()
    if (!identity) return []
    const principal = await ctx.db.query("principals").withIndex("by_external_subject", (q) => q.eq("externalSubject", identity.subject)).unique()
    const organizations = principal?.organizationId
      ? [await ctx.db.get(principal.organizationId)].filter((item) => item !== null)
      : await ctx.db.query("organizations").take(100)
    return organizations.map((item) => ({ id: item.publicId, name: item.name, industry: item.industry, timezone: item.timezone, countryCode: item.countryCode, status: item.status }))
  },
})

export const publish = internalMutation({
  args: { organizationPublicId: v.string(), principalId: v.id("principals"), explicitConsent: v.boolean() },
  returns: v.object({ organizationId: v.string(), status: organizationStatus }),
  handler: async (ctx, args) => {
    if (!args.explicitConsent) fail("INVALID_INPUT", "Explicit publication consent is required")
    const organization = await ctx.db.query("organizations").withIndex("by_public_id", (q) => q.eq("publicId", args.organizationPublicId)).unique()
    if (!organization) fail("NOT_FOUND", "Organization not found")
    const principal = await ctx.db.get(args.principalId)
    if (!principal || principal.organizationId !== organization._id) fail("TENANT_SCOPE_VIOLATION", "Principal does not belong to this organization")
    const now = Date.now()
    const services = await ctx.db.query("services").withIndex("by_organization_status", (q) => q.eq("organizationId", organization._id).eq("status", "active")).take(1)
    const locations = await ctx.db.query("locations").withIndex("by_organization", (q) => q.eq("organizationId", organization._id)).take(1)
    if (!services.length || !locations.length) fail("MISSING_REQUIRED_FIELDS", "At least one active service and location are required")
    const onboarding = await ctx.db.query("onboardingSessions").withIndex("by_organization", (q) => q.eq("organizationId", organization._id)).first()
    if (!onboarding?.emailVerifiedAt) fail("MISSING_REQUIRED_FIELDS", "Owner email OTP verification is required")
    const chatwootSteps = await ctx.db.query("integrationProvisioning").withIndex("by_organization_provider", (q) => q.eq("organizationId", organization._id).eq("provider", "chatwoot")).collect()
    const evolutionSteps = await ctx.db.query("integrationProvisioning").withIndex("by_organization_provider", (q) => q.eq("organizationId", organization._id).eq("provider", "evolution")).collect()
    if (!chatwootSteps.some((item) => item.step === "account" && item.state === "connected") || !chatwootSteps.some((item) => item.step === "technical_user" && item.state === "connected") || !chatwootSteps.some((item) => item.step === "agent_bot" && item.state === "connected") || !evolutionSteps.some((item) => item.step === "baileys_instance" && item.state === "connected")) {
      fail("MISSING_REQUIRED_FIELDS", "Chatwoot, technical user, Agent Bot and WhatsApp connection must be verified before publication")
    }
    await ctx.db.patch(organization._id, { status: "published", publishedAt: now, updatedAt: now })
    if (onboarding) await ctx.db.patch(onboarding._id, { explicitPublishConsentAt: now, state: "published", updatedAt: now })
    return { organizationId: organization.publicId, status: "published" as const }
  },
})

export const linkCurrentIdentity = mutation({
  args: { principalPublicId: v.string() },
  returns: v.string(),
  handler: async (ctx, args) => {
    const identity = await ctx.auth.getUserIdentity()
    if (!identity) fail("AUTHENTICATION_REQUIRED", "Sign in before linking an identity")
    const principal = await ctx.db.query("principals").withIndex("by_public_id", (q) => q.eq("publicId", args.principalPublicId)).unique()
    if (!principal || principal.type !== "human") fail("NOT_FOUND", "Human principal not found")
    await ctx.db.patch(principal._id, { externalSubject: identity.subject, updatedAt: Date.now() })
    return principal.publicId
  },
})

export const onboardingContext = internalQuery({
  args: { onboardingPublicId: v.string() },
  returns: v.union(v.null(), v.object({ id: v.id("onboardingSessions"), publicId: v.string(), organizationPublicId: v.string(), ownerEmail: v.string(), ownerPhoneE164: v.string(), phoneAllowed: v.boolean(), webhookVerified: v.boolean(), emailVerifiedAt: v.optional(v.number()) })),
  handler: async (ctx, args) => {
    const session = await ctx.db.query("onboardingSessions").withIndex("by_public_id", (q) => q.eq("publicId", args.onboardingPublicId)).unique()
    if (!session) return null
    const organization = await ctx.db.get(session.organizationId)
    if (!organization) return null
    return { id: session._id, publicId: session.publicId, organizationPublicId: organization.publicId, ownerEmail: session.ownerEmail, ownerPhoneE164: session.ownerPhoneE164, phoneAllowed: session.phoneAllowed, webhookVerified: session.webhookVerified, emailVerifiedAt: session.emailVerifiedAt }
  },
})

export const storeOtp = internalMutation({
  args: { onboardingId: v.id("onboardingSessions"), otpHash: v.string(), expiresAt: v.number() },
  returns: v.null(),
  handler: async (ctx, args) => {
    const session = await ctx.db.get(args.onboardingId)
    if (!session || !session.phoneAllowed || !session.webhookVerified) fail("AUTHENTICATION_REQUIRED", "Onboarding source is not verified")
    await ctx.db.patch(session._id, { emailOtpHash: args.otpHash, emailOtpExpiresAt: args.expiresAt, updatedAt: Date.now() })
    return null
  },
})

export const verifyOtp = internalMutation({
  args: { onboardingPublicId: v.string(), otpHash: v.string() },
  returns: v.object({ verified: v.boolean(), organizationPublicId: v.optional(v.string()) }),
  handler: async (ctx, args) => {
    const session = await ctx.db.query("onboardingSessions").withIndex("by_public_id", (q) => q.eq("publicId", args.onboardingPublicId)).unique()
    if (!session || !session.emailOtpHash || !session.emailOtpExpiresAt || session.emailOtpExpiresAt <= Date.now() || session.emailOtpHash !== args.otpHash) return { verified: false }
    const organization = await ctx.db.get(session.organizationId)
    const now = Date.now()
    await ctx.db.patch(session._id, { emailVerifiedAt: now, emailOtpHash: undefined, emailOtpExpiresAt: undefined, state: "verified_owner", completedSteps: [...new Set([...session.completedSteps, "owner_email_verified"])], updatedAt: now })
    return { verified: true, organizationPublicId: organization?.publicId }
  },
})
