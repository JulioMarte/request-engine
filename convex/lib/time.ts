export type ShiftName = "morning" | "afternoon" | "evening"

export function assertLocalDate(value: string) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) throw new Error("localDate must use YYYY-MM-DD")
}

export function addLocalDays(localDate: string, days: number) {
  assertLocalDate(localDate)
  const [year, month, day] = localDate.split("-").map(Number)
  const date = new Date(Date.UTC(year, month - 1, day + days))
  return date.toISOString().slice(0, 10)
}

export function weekday(localDate: string) {
  assertLocalDate(localDate)
  const [year, month, day] = localDate.split("-").map(Number)
  return new Date(Date.UTC(year, month - 1, day)).getUTCDay()
}

function localParts(epochMs: number, timeZone: string) {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  }).formatToParts(new Date(epochMs))
  const read = (type: Intl.DateTimeFormatPartTypes) => Number(parts.find((part) => part.type === type)?.value)
  return { year: read("year"), month: read("month"), day: read("day"), hour: read("hour"), minute: read("minute"), second: read("second") }
}

export function zonedDateTimeToUtc(localDate: string, minuteOfDay: number, timeZone: string) {
  assertLocalDate(localDate)
  if (minuteOfDay < 0 || minuteOfDay > 1440) throw new Error("minuteOfDay must be between 0 and 1440")
  const [year, month, day] = localDate.split("-").map(Number)
  const hour = Math.floor(minuteOfDay / 60)
  const minute = minuteOfDay % 60
  const desired = Date.UTC(year, month - 1, day, hour, minute)
  let candidate = desired
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const actual = localParts(candidate, timeZone)
    const represented = Date.UTC(actual.year, actual.month - 1, actual.day, actual.hour, actual.minute, actual.second)
    candidate += desired - represented
  }
  const finalParts = localParts(candidate, timeZone)
  if (finalParts.year !== year || finalParts.month !== month || finalParts.day !== day || finalParts.hour !== hour || finalParts.minute !== minute) {
    throw new Error("The requested local time does not exist in this timezone")
  }
  return candidate
}

export function shiftForMinute(minute: number): ShiftName {
  if (minute < 12 * 60) return "morning"
  if (minute < 17 * 60) return "afternoon"
  return "evening"
}

export function localLabel(epochMs: number, timeZone: string, locale = "es-DO") {
  return new Intl.DateTimeFormat(locale, { timeZone, dateStyle: "medium", timeStyle: "short" }).format(new Date(epochMs))
}

export function localDateAndMinute(epochMs: number, timeZone: string) {
  const parts = localParts(epochMs, timeZone)
  return { localDate: `${parts.year.toString().padStart(4, "0")}-${parts.month.toString().padStart(2, "0")}-${parts.day.toString().padStart(2, "0")}`, minuteOfDay: parts.hour * 60 + parts.minute }
}

export function clampToContactWindow(epochMs: number, timeZone: string, startMinute: number, endMinute: number) {
  const local = localDateAndMinute(epochMs, timeZone)
  if (local.minuteOfDay < startMinute) return zonedDateTimeToUtc(local.localDate, startMinute, timeZone)
  if (local.minuteOfDay >= endMinute) return zonedDateTimeToUtc(addLocalDays(local.localDate, 1), startMinute, timeZone)
  return epochMs
}
