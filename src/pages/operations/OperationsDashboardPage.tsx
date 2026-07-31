import { useQuery } from "convex/react"
import { NavLink } from "react-router-dom"
import { Activity, Bot, CalendarDays, CheckCircle2, Clock3, MessageSquareMore, UsersRound } from "lucide-react"
import { api } from "../../../convex/_generated/api"
import { config } from "@/app/config"
import { PageContainer } from "@/components/layout/PageContainer"
import { PageHeader } from "@/components/layout/PageHeader"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

const statusLabel: Record<string, string> = {
  pending_confirmation: "Por confirmar",
  confirmed: "Confirmada",
  checked_in: "En recepción",
  in_service: "En atención",
  completed: "Completada",
  cancelled_unconfirmed: "Liberada",
}

type UpcomingRow = { id: string; personName: string; serviceName: string; startsAt: number; status: string; mode: string }
type QueueRow = { id: string; ticketNumber: number; personName: string; serviceName: string; checkedInAt: number; priorityRank: number }

function metric(value: number, label: string, detail: string, Icon: typeof CalendarDays) {
  return (
    <Card>
      <CardContent className="flex items-start justify-between gap-3 pt-4">
        <div>
          <p className="text-2xl font-semibold tracking-tight">{value}</p>
          <p className="mt-1 text-sm font-medium">{label}</p>
          <p className="mt-1 text-xs text-muted-foreground">{detail}</p>
        </div>
        <span className="rounded-lg bg-emerald-50 p-2.5 text-primary"><Icon className="h-5 w-5" aria-hidden="true" /></span>
      </CardContent>
    </Card>
  )
}

export function OperationsDashboardPage() {
  if (!config.convexUrl) {
    return (
      <PageContainer>
        <PageHeader title="Operación de agenda" description="Configura VITE_CONVEX_URL para conectar el panel con la fuente de verdad." />
      </PageContainer>
    )
  }
  return <ConnectedOperationsDashboard />
}

function ConnectedOperationsDashboard() {
  const data = useQuery(api.v1Dashboard.snapshot, {})
  const loading = data === undefined

  return (
    <PageContainer>
      <PageHeader
        eyebrow="Centro operativo"
        title={data?.organization.name ?? "Operación de agenda"}
        description="Citas, confirmaciones y turnos en una sola vista. Convex es la fuente de verdad; Chatwoot conserva la conversación."
        actions={<Badge variant={data?.organization.status === "published" ? "success" : "warning"}>{data?.organization.status === "published" ? "Publicado" : loading ? "Cargando" : "Borrador"}</Badge>}
      />

      {!loading && !data && (
        <Card className="border-dashed">
          <CardContent className="py-10 text-center">
            <Bot className="mx-auto h-8 w-8 text-primary" aria-hidden="true" />
            <h2 className="mt-3 text-base font-semibold">Comienza con el bot de onboarding</h2>
            <p className="mx-auto mt-2 max-w-lg text-sm leading-6 text-muted-foreground">La organización permanecerá en borrador hasta tener sede, servicio, horario y una confirmación explícita para publicar.</p>
            <NavLink className="mt-5 inline-flex min-h-11 items-center rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground" to="/admin/tenants">Preparar organización</NavLink>
          </CardContent>
        </Card>
      )}

      {data && (
        <>
          <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4" aria-label="Métricas de operación">
            {metric(data.metrics.todayBookings, "Citas de hoy", "Incluye todos los modos", CalendarDays)}
            {metric(data.metrics.pendingConfirmation, "Por confirmar", "Ocupan capacidad", MessageSquareMore)}
            {metric(data.metrics.waitingNow, "Esperando ahora", "Tickets con check-in", UsersRound)}
            {metric(data.metrics.upcomingWeek, "Próximos 7 días", "Carga confirmada y pendiente", Activity)}
          </section>

          <div className="mt-4 grid gap-4 xl:grid-cols-[1.35fr_0.9fr]">
            <Card>
              <CardHeader className="flex-row items-start justify-between gap-4">
                <div>
                  <CardTitle>Próximas citas</CardTitle>
                  <CardDescription>Hora local de {data.organization.timezone}</CardDescription>
                </div>
                <NavLink className="text-sm font-medium text-primary hover:underline" to="/operations/bookings">Ver agenda</NavLink>
              </CardHeader>
              <CardContent>
                {data.upcoming.length ? (
                  <div className="divide-y" role="list">
                    {data.upcoming.map((booking: UpcomingRow) => (
                      <div className="grid gap-2 py-3 sm:grid-cols-[92px_1fr_auto] sm:items-center" key={booking.id} role="listitem">
                        <div>
                          <p className="text-sm font-semibold">{new Intl.DateTimeFormat("es-DO", { hour: "numeric", minute: "2-digit", timeZone: data.organization.timezone }).format(booking.startsAt)}</p>
                          <p className="text-xs text-muted-foreground">{new Intl.DateTimeFormat("es-DO", { month: "short", day: "numeric", timeZone: data.organization.timezone }).format(booking.startsAt)}</p>
                        </div>
                        <div className="min-w-0">
                          <p className="truncate text-sm font-medium">{booking.personName}</p>
                          <p className="truncate text-xs text-muted-foreground">{booking.serviceName} · {booking.mode === "arrival_window" ? "orden de llegada" : booking.mode === "class_session" ? "clase" : "hora fija"}</p>
                        </div>
                        <Badge variant={booking.status === "confirmed" ? "success" : "warning"}>{statusLabel[booking.status] ?? booking.status}</Badge>
                      </div>
                    ))}
                  </div>
                ) : <p className="py-8 text-center text-sm text-muted-foreground">No hay citas próximas.</p>}
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="flex-row items-start justify-between gap-4">
                <div>
                  <CardTitle>Cola en vivo</CardTitle>
                  <CardDescription>El ticket nace al hacer check-in</CardDescription>
                </div>
                <NavLink className="text-sm font-medium text-primary hover:underline" to="/operations/queue">Abrir cola</NavLink>
              </CardHeader>
              <CardContent>
                {data.queue.length ? (
                  <div className="space-y-2">
                    {data.queue.slice(0, 6).map((entry: QueueRow, index: number) => (
                      <div className="flex items-center gap-3 rounded-md border p-3" key={entry.id}>
                        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-muted text-sm font-semibold">{entry.ticketNumber}</span>
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-sm font-medium">{entry.personName}</p>
                          <p className="truncate text-xs text-muted-foreground">{entry.serviceName}</p>
                        </div>
                        <span className="text-xs text-muted-foreground">{index === 0 ? "Siguiente" : `${index} delante`}</span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="py-8 text-center">
                    <CheckCircle2 className="mx-auto h-7 w-7 text-primary" aria-hidden="true" />
                    <p className="mt-2 text-sm font-medium">Recepción al día</p>
                    <p className="mt-1 text-xs text-muted-foreground">No hay personas esperando.</p>
                  </div>
                )}
                <div className="mt-3 flex items-start gap-2 rounded-md bg-muted p-3 text-xs leading-5 text-muted-foreground">
                  <Clock3 className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                  La espera es una estimación dinámica, nunca un turno garantizado antes del check-in.
                </div>
              </CardContent>
            </Card>
          </div>
        </>
      )}
    </PageContainer>
  )
}
