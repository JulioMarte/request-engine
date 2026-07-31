import { describe, expect, it } from "vitest"
import { canAutoRelease, intervalsOverlap } from "../convex/lib/confirmationPolicy"

describe("automatic confirmation release", () => {
  const base = { autoReleaseUnconfirmed: true, neverAutoCancel: false, warned: true, alternateChannelRequired: true }

  it("never releases after delivery failures only", () => {
    expect(canAutoRelease({ ...base, deliveries: [{ channel: "whatsapp", status: "failed" }, { channel: "voice", status: "failed" }] })).toBe(false)
  })

  it("requires a delivered contact and an attempted alternate channel", () => {
    expect(canAutoRelease({ ...base, deliveries: [{ channel: "whatsapp", status: "delivered" }] })).toBe(false)
    expect(canAutoRelease({ ...base, deliveries: [{ channel: "whatsapp", status: "delivered" }, { channel: "voice", status: "failed" }] })).toBe(true)
  })

  it("honors never-auto-cancel and warning safeguards", () => {
    const deliveries = [{ channel: "whatsapp", status: "delivered" as const }, { channel: "voice", status: "dispatched" as const }]
    expect(canAutoRelease({ ...base, neverAutoCancel: true, deliveries })).toBe(false)
    expect(canAutoRelease({ ...base, warned: false, deliveries })).toBe(false)
  })
})

describe("half-open allocation intervals", () => {
  it("allows adjacent appointments and blocks real overlap", () => {
    expect(intervalsOverlap(100, 200, 200, 300)).toBe(false)
    expect(intervalsOverlap(100, 201, 200, 300)).toBe(true)
  })
})

