import { Bot, Hand, Pause, Play, UserRound } from "lucide-react"
import { Button } from "@/components/ui/button"
import { aiModeLabels, type AiMode } from "@/features/ai-control/lib/ai-mode"

const modes: Array<{ mode: AiMode; icon: typeof Bot }> = [
  { mode: "auto", icon: Play },
  { mode: "paused", icon: Pause },
  { mode: "manual", icon: Hand },
  { mode: "handoff", icon: UserRound },
]

export function AiModeSwitcher({ mode, onChange }: { mode: AiMode; onChange: (mode: AiMode) => void }) {
  return (
    <div className="grid grid-cols-2 gap-2">
      {modes.map((item) => (
        <Button
          key={item.mode}
          onClick={() => onChange(item.mode)}
          variant={mode === item.mode ? "default" : "outline"}
          size="sm"
          title={aiModeLabels[item.mode]}
        >
          <item.icon className="h-4 w-4" aria-hidden="true" />
          {aiModeLabels[item.mode]}
        </Button>
      ))}
    </div>
  )
}
