import { cronJobs } from "convex/server"
import { internal } from "./_generated/api"

const crons = cronJobs()

crons.interval("dispatch transactional outbox", { minutes: 1 }, internal.v1Outbox.dispatch, {})
crons.interval("release safely unconfirmed bookings", { minutes: 5 }, internal.v1Bookings.autoReleaseDue, {})
crons.daily("prepare holiday opening reviews", { hourUTC: 12, minuteUTC: 0 }, internal.v1Holidays.prepareSevenDayReviews, {})

export default crons
