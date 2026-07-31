import { describe, expect, it } from "vitest"
import { addLocalDays, clampToContactWindow, shiftForMinute, weekday, zonedDateTimeToUtc } from "../convex/lib/time"

describe("timezone conversion", () => {
  it("keeps Santo Domingo at UTC-4 without daylight saving", () => {
    expect(new Date(zonedDateTimeToUtc("2026-07-31", 9 * 60, "America/Santo_Domingo")).toISOString()).toBe("2026-07-31T13:00:00.000Z")
    expect(new Date(zonedDateTimeToUtc("2026-12-31", 9 * 60, "America/Santo_Domingo")).toISOString()).toBe("2026-12-31T13:00:00.000Z")
  })

  it("accounts for US daylight saving changes", () => {
    expect(new Date(zonedDateTimeToUtc("2026-01-15", 9 * 60, "America/New_York")).toISOString()).toBe("2026-01-15T14:00:00.000Z")
    expect(new Date(zonedDateTimeToUtc("2026-07-15", 9 * 60, "America/New_York")).toISOString()).toBe("2026-07-15T13:00:00.000Z")
  })

  it("rejects a local time skipped by the DST spring transition", () => {
    expect(() => zonedDateTimeToUtc("2026-03-08", 2 * 60 + 30, "America/New_York")).toThrow("does not exist")
  })
})

describe("local calendar helpers", () => {
  it("crosses month and year boundaries without server timezone leakage", () => {
    expect(addLocalDays("2026-12-31", 1)).toBe("2027-01-01")
    expect(weekday("2026-08-02")).toBe(0)
  })

  it("maps business shifts", () => {
    expect(shiftForMinute(9 * 60)).toBe("morning")
    expect(shiftForMinute(14 * 60)).toBe("afternoon")
    expect(shiftForMinute(19 * 60)).toBe("evening")
  })

  it("moves contact attempts into the next valid local window", () => {
    const late = Date.parse("2026-07-31T01:30:00.000Z") // 21:30 in Santo Domingo
    expect(new Date(clampToContactWindow(late, "America/Santo_Domingo", 9 * 60, 20 * 60)).toISOString()).toBe("2026-07-31T13:00:00.000Z")
  })
})
