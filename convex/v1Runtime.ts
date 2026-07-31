import { v } from "convex/values"
import { internalQuery } from "./_generated/server"
import { bookingMode, modality } from "./domainValidators"
import { fail } from "./lib/errors"

export const bundle = internalQuery({
  args: { organizationPublicId: v.string() },
  returns: v.object({ organization: v.object({ id: v.string(), name: v.string(), industry: v.string(), locale: v.string(), timezone: v.string() }), basePrompt: v.string(), organizationPrompt: v.string(), tools: v.array(v.object({ name: v.string(), description: v.string(), maxResults: v.number() })), catalogHints: v.array(v.object({ serviceId: v.string(), name: v.string(), bookingMode, modalities: v.array(modality) })), rules: v.array(v.string()), version: v.number() }),
  handler: async (ctx, args) => {
    const organization = await ctx.db.query("organizations").withIndex("by_public_id", (q) => q.eq("publicId", args.organizationPublicId)).unique()
    if (!organization) fail("NOT_FOUND", "Organization not found")
    const prompts = await ctx.db.query("promptVersions").withIndex("by_organization_layer_status", (q) => q.eq("organizationId", organization._id).eq("layer", "organization").eq("status", "published")).collect()
    const toolManifest = await ctx.db.query("toolManifests").withIndex("by_organization_status", (q) => q.eq("organizationId", organization._id).eq("status", "published")).first()
    const services = await ctx.db.query("services").withIndex("by_organization_status", (q) => q.eq("organizationId", organization._id).eq("status", "active")).take(5)
    return {
      organization: { id: organization.publicId, name: organization.name, industry: organization.industry, locale: organization.locale, timezone: organization.timezone },
      basePrompt: "Eres un agente de agenda. Nunca inventes servicios, precios, disponibilidad, turnos ni feriados. Consulta tools y crea reservas solo con un offerId vigente. Si faltan datos, pregunta una cosa a la vez.",
      organizationPrompt: prompts.sort((a, b) => b.version - a.version)[0]?.content ?? "Mantén el tono profesional definido por la organización y escala ambigüedades a una persona.",
      tools: toolManifest?.tools.filter((tool) => tool.enabled).map((tool) => ({ name: tool.name, description: tool.description, maxResults: Math.min(tool.maxResults, 5) })) ?? [
        { name: "catalog.search", description: "Busca hasta cinco servicios reales.", maxResults: 5 },
        { name: "availability.summarize", description: "Resume días y turnos disponibles.", maxResults: 5 },
        { name: "availability.listOptions", description: "Emite hasta cinco ofertas reservables.", maxResults: 5 },
        { name: "booking.create", description: "Reserva una oferta vigente con idempotencia.", maxResults: 1 },
      ],
      catalogHints: services.map((service) => ({ serviceId: service.publicId, name: service.name, bookingMode: service.bookingMode, modalities: service.modalities })),
      rules: ["No expongas identificadores ni afiliaciones sin scope de PII.", "No afirmes que una estimación de cola es un turno garantizado.", "Una transcripción libre nunca cambia una reserva; usa una tool estructurada."],
      version: toolManifest?.version ?? 1,
    }
  },
})

