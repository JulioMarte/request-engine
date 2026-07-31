import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import type { ChatwootDashboardContext } from "@/features/chatwoot/lib/chatwoot-types"

export function ConversationHeaderCard({ context }: { context: ChatwootDashboardContext | null }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Conversacion activa</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <div>
          <p className="font-medium">{context?.contactName ?? "Sin contacto seleccionado"}</p>
          <p className="text-xs text-muted-foreground">{context?.contactPhone ?? "Telefono no disponible"}</p>
        </div>
        <div className="grid grid-cols-2 gap-2 text-xs text-muted-foreground">
          <span>Cuenta: {context?.accountId ?? "-"}</span>
          <span>Inbox: {context?.inboxId ?? "-"}</span>
          <span>Conversacion: {context?.conversationId ?? "-"}</span>
          <span>Contacto: {context?.contactId ?? "-"}</span>
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge variant="outline">{context?.conversationStatus ?? "unknown"}</Badge>
          {(context?.labels ?? []).slice(0, 4).map((label) => (
            <Badge key={label} variant="secondary">{label}</Badge>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}
