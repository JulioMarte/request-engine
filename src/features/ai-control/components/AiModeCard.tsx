import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { AiModeSwitcher } from "@/features/ai-control/components/AiModeSwitcher"
import { aiModeLabels, type AiMode } from "@/features/ai-control/lib/ai-mode"

type AiModeCardProps = {
  mode: AiMode
  lastEvent: string
  summary: string
  onChange: (mode: AiMode) => void
}

export function AiModeCard({ mode, lastEvent, summary, onChange }: AiModeCardProps) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <div>
            <CardTitle>AI Control</CardTitle>
            <CardDescription>{lastEvent}</CardDescription>
          </div>
          <Badge variant={mode === "auto" ? "success" : "warning"}>{aiModeLabels[mode]}</Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-xs text-muted-foreground">{summary}</p>
        <AiModeSwitcher mode={mode} onChange={onChange} />
      </CardContent>
    </Card>
  )
}
