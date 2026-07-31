import { useQuery } from "convex/react"
import { CalendarClock } from "lucide-react"
import { api } from "../../../convex/_generated/api"
import { config } from "@/app/config"
import { PageContainer } from "@/components/layout/PageContainer"
import { PageHeader } from "@/components/layout/PageHeader"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"

type BookingRow = { bookingId: string; serviceName: string; status: string; startsAt: string; localDate: string; timezone: string; participantCount: number; mode: string }

export function BookingsPage() {
  if (!config.convexUrl) return <PageContainer><PageHeader title="Agenda" description="Conecta Convex para cargar reservas." /></PageContainer>
  return <ConnectedBookings />
}

function ConnectedBookings() {
  const snapshot = useQuery(api.v1Dashboard.snapshot, {})
  const bookings = useQuery(api.v1Bookings.listUpcoming, snapshot?.organization.id ? { organizationPublicId: snapshot.organization.id, limit: 100 } : "skip")
  return (
    <PageContainer>
      <PageHeader eyebrow="Agenda" title="Reservas y clases" description="Estados explícitos, participantes y capacidad desde una sola fuente de verdad." />
      <Card>
        <CardContent className="overflow-x-auto pt-4">
          {bookings?.length ? (
            <table className="w-full min-w-[720px] text-left text-sm">
              <thead className="border-b text-xs uppercase tracking-wide text-muted-foreground"><tr><th className="pb-3 font-medium">Fecha</th><th className="pb-3 font-medium">Servicio</th><th className="pb-3 font-medium">Modo</th><th className="pb-3 font-medium">Personas</th><th className="pb-3 text-right font-medium">Estado</th></tr></thead>
              <tbody className="divide-y">{bookings.map((booking: BookingRow) => <tr key={booking.bookingId}><td className="py-4 font-medium">{new Intl.DateTimeFormat("es-DO", { dateStyle: "medium", timeStyle: "short", timeZone: booking.timezone }).format(new Date(booking.startsAt))}</td><td className="py-4">{booking.serviceName}</td><td className="py-4 text-muted-foreground">{booking.mode === "arrival_window" ? "Orden de llegada" : booking.mode === "class_session" ? "Clase" : "Hora fija"}</td><td className="py-4">{booking.participantCount}</td><td className="py-4 text-right"><Badge variant={booking.status === "confirmed" ? "success" : "warning"}>{booking.status.replaceAll("_", " ")}</Badge></td></tr>)}</tbody>
            </table>
          ) : <div className="py-12 text-center"><CalendarClock className="mx-auto h-8 w-8 text-primary" aria-hidden="true" /><p className="mt-3 font-medium">Todavía no hay reservas</p><p className="mt-1 text-sm text-muted-foreground">Las reservas creadas por agentes aparecerán aquí en tiempo real.</p></div>}
        </CardContent>
      </Card>
    </PageContainer>
  )
}
