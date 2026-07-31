import { aiModes } from "@/lib/constants"

export type AiMode = (typeof aiModes)[number]

export const aiModeLabels: Record<AiMode, string> = {
  auto: "Automático",
  manual: "Manual",
  handoff: "Derivar",
  paused: "Pausado",
  disabled: "Desactivado",
}
