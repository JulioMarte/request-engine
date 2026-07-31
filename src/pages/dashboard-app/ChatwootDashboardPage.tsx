import { CalendarCheck, ClipboardList, MessageSquareText } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { EmptyState } from "@/components/common/EmptyState"
import { PageContainer } from "@/components/layout/PageContainer"
import { PageHeader } from "@/components/layout/PageHeader"
import { Button } from "@/components/ui/button"
import { AiModeCard } from "@/features/ai-control/components/AiModeCard"
import { useAiState } from "@/features/ai-control/hooks/useAiState"
import { ChatwootContextDebug } from "@/features/chatwoot/components/ChatwootContextDebug"
import { ConversationHeaderCard } from "@/features/chatwoot/components/ConversationHeaderCard"
import { useChatwootContext } from "@/features/chatwoot/hooks/useChatwootContext"

export function ChatwootDashboardPage() {
  const chatwoot = useChatwootContext()
  const ai = useAiState(chatwoot.context)

  return (
    <PageContainer>
      <PageHeader
        description="Controla la solicitud, el modo de IA y las proximas acciones de la conversacion actual."
        title="Dashboard operativo"
        actions={
        <Badge variant={chatwoot.isConnected ? "success" : "warning"}>
          {chatwoot.isConnected ? "Conectado" : chatwoot.isEmbedded ? "Esperando contexto" : "Modo standalone"}
        </Badge>
        }
      />

      {!chatwoot.isEmbedded && (
        <div className="mb-4">
          <EmptyState
            title="No esta embebido en Chatwoot"
            description="La pagina sirve para desarrollo, pero en produccion el contexto llega por postMessage desde Chatwoot."
          />
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[1fr_360px]">
        <div className="space-y-4">
          <ConversationHeaderCard context={chatwoot.context} />
          <Card>
            <CardHeader>
              <CardTitle>Solicitud actual</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-3 text-sm sm:grid-cols-3">
              <div className="rounded-md bg-muted p-3">
                <ClipboardList className="mb-2 h-4 w-4 text-primary" aria-hidden="true" />
                <p className="text-xs text-muted-foreground">Intencion</p>
                <p className="font-medium">Sin solicitud detectada</p>
              </div>
              <div className="rounded-md bg-muted p-3">
                <MessageSquareText className="mb-2 h-4 w-4 text-primary" aria-hidden="true" />
                <p className="text-xs text-muted-foreground">Estado</p>
                <p className="font-medium">Nueva</p>
              </div>
              <div className="rounded-md bg-muted p-3">
                <CalendarCheck className="mb-2 h-4 w-4 text-primary" aria-hidden="true" />
                <p className="text-xs text-muted-foreground">Siguiente accion</p>
                <p className="font-medium">Esperar mensaje</p>
              </div>
            </CardContent>
          </Card>
          <ChatwootContextDebug context={chatwoot.context} />
        </div>
        <div className="space-y-4">
          <AiModeCard
            lastEvent={ai.state.lastEvent}
            mode={ai.state.mode}
            onChange={ai.setMode}
            summary={ai.state.summary}
          />
          <Card>
            <CardHeader>
              <CardTitle>Acciones rapidas</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              <Button className="w-full justify-start" variant="outline" disabled>
                Crear cita
              </Button>
              <Button className="w-full justify-start" variant="outline" disabled>
                Preparar cotizacion
              </Button>
              <Button className="w-full justify-start" variant="outline" disabled>
                Derivar a operador
              </Button>
              <p className="text-xs leading-5 text-muted-foreground">
                Las acciones se habilitan cuando exista una solicitud activa.
              </p>
            </CardContent>
          </Card>
        </div>
      </div>
    </PageContainer>
  )
}
