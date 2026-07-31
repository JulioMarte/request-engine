import { useQuery } from "convex/react"
import { QrCode, UsersRound } from "lucide-react"
import { api } from "../../../convex/_generated/api"
import { config } from "@/app/config"
import { PageContainer } from "@/components/layout/PageContainer"
import { PageHeader } from "@/components/layout/PageHeader"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

type QueueRow = { id: string; ticketNumber: number; personName: string; serviceName: string; checkedInAt: number; priorityRank: number }

export function QueuePage() {
  if (!config.convexUrl) return <PageContainer><PageHeader title="Cola en vivo" description="Conecta Convex para ver los turnos." /></PageContainer>
  return <ConnectedQueue />
}

function ConnectedQueue() {
  const data = useQuery(api.v1Dashboard.snapshot, {})
  return (
    <PageContainer>
      <PageHeader eyebrow="Recepción" title="Cola en vivo" description="FIFO por check-in, con prioridad manual únicamente cuando existe motivo y auditoría." actions={<Badge variant="outline">Actualización en tiempo real</Badge>} />
      <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
        <Card>
          <CardHeader><CardTitle>Personas esperando</CardTitle><CardDescription>El número es estable; personas delante y espera son dinámicos.</CardDescription></CardHeader>
          <CardContent>
            {data?.queue.length ? <div className="divide-y">{data.queue.map((entry: QueueRow, index: number) => <div className="grid grid-cols-[56px_1fr_auto] items-center gap-3 py-3" key={entry.id}><span className="flex h-11 w-11 items-center justify-center rounded-md bg-primary font-semibold text-primary-foreground">{entry.ticketNumber}</span><div><p className="text-sm font-medium">{entry.personName}</p><p className="text-xs text-muted-foreground">{entry.serviceName} · check-in {new Intl.DateTimeFormat("es-DO", { hour: "numeric", minute: "2-digit" }).format(entry.checkedInAt)}</p></div><div className="text-right"><p className="text-sm font-medium">{index === 0 ? "Siguiente" : `${index} delante`}</p><p className="text-xs text-muted-foreground">estimado</p></div></div>)}</div> : <div className="py-12 text-center"><UsersRound className="mx-auto h-8 w-8 text-primary" aria-hidden="true" /><p className="mt-3 font-medium">No hay personas esperando</p><p className="mt-1 text-sm text-muted-foreground">Los check-ins aparecerán aquí de inmediato.</p></div>}
          </CardContent>
        </Card>
        <Card className="h-fit">
          <CardHeader><CardTitle>Check-in por QR</CardTitle><CardDescription>El token es opaco, revocable y expira.</CardDescription></CardHeader>
          <CardContent><div className="flex aspect-square items-center justify-center rounded-lg border border-dashed bg-muted"><QrCode className="h-20 w-20 text-muted-foreground" aria-label="Marcador para código QR de check-in" /></div><p className="mt-3 text-xs leading-5 text-muted-foreground">La recepción también puede escanear el código del paciente. La prioridad no cambia sin permiso, motivo y evento de auditoría.</p></CardContent>
        </Card>
      </div>
    </PageContainer>
  )
}
