import { aiModes } from "@/lib/constants"

export type AiMode = (typeof aiModes)[number]

export const aiModeLabels: Record<AiMode, string> = {
  auto: "Auto",
  manual: "Manual",
  handoff: "Handoff",
  paused: "Paused",
  disabled: "Disabled",
}
