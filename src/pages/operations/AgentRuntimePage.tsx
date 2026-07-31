import { Bot, Braces, KeyRound, ShieldCheck, Webhook } from "lucide-react"
import { PageContainer } from "@/components/layout/PageContainer"
import { PageHeader } from "@/components/layout/PageHeader"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

const tools = [
  ["catalog.search", "Busca servicios reales", "5 resultados"],
  ["availability.summarize", "Reduce días a turnos", "14 días"],
  ["availability.listOptions", "Emite ofertas verificadas", "5 opciones"],
  ["booking.create", "Consume una oferta con idempotencia", "1 reserva"],
]

export function AgentRuntimePage() {
  return (
    <PageContainer>
      <PageHeader eyebrow="Automatización" title="Runtime para agentes" description="El modelo conversa; Convex decide disponibilidad, capacidad y estados." actions={<Badge variant="success">Contrato v1</Badge>} />
      <div className="grid gap-4 lg:grid-cols-[1.1fr_0.9fr]">
        <Card>
          <CardHeader><CardTitle>Tool manifest</CardTitle><CardDescription>Progresión obligatoria para evitar horarios inventados.</CardDescription></CardHeader>
          <CardContent className="space-y-2">{tools.map(([name, description, limit], index) => <div className="grid grid-cols-[32px_1fr_auto] items-center gap-3 rounded-md border p-3" key={name}><span className="flex h-8 w-8 items-center justify-center rounded-md bg-muted text-xs font-semibold">{index + 1}</span><div><p className="font-mono text-xs font-semibold">{name}</p><p className="mt-1 text-xs text-muted-foreground">{description}</p></div><Badge variant="neutral">{limit}</Badge></div>)}</CardContent>
        </Card>
        <div className="space-y-4">
          <Card><CardHeader><CardTitle>Fronteras de seguridad</CardTitle></CardHeader><CardContent className="space-y-3 text-sm"><p className="flex gap-2"><ShieldCheck className="h-5 w-5 shrink-0 text-primary" aria-hidden="true" /><span>Las API keys tienen organización, scopes, expiración, rotación y revocación.</span></p><p className="flex gap-2"><KeyRound className="h-5 w-5 shrink-0 text-primary" aria-hidden="true" /><span>Los secretos completos nunca vuelven a mostrarse en el panel.</span></p><p className="flex gap-2"><Webhook className="h-5 w-5 shrink-0 text-primary" aria-hidden="true" /><span>Los callbacks externos requieren firma HMAC e intención tipada.</span></p></CardContent></Card>
          <Card><CardHeader><CardTitle>Superficies publicadas</CardTitle></CardHeader><CardContent><div className="flex items-center gap-3 rounded-md bg-muted p-3"><Braces className="h-5 w-5 text-primary" aria-hidden="true" /><div><p className="text-sm font-medium">OpenAPI 3.1</p><p className="text-xs text-muted-foreground">GET /v1/openapi.json</p></div></div><div className="mt-2 flex items-center gap-3 rounded-md bg-muted p-3"><Bot className="h-5 w-5 text-primary" aria-hidden="true" /><div><p className="text-sm font-medium">Runtime bundle</p><p className="text-xs text-muted-foreground">Prompts publicados + tools + contexto mínimo</p></div></div></CardContent></Card>
        </div>
      </div>
    </PageContainer>
  )
}

