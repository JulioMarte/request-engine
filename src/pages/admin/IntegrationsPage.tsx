import { PlugZap } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { PageContainer } from "@/components/layout/PageContainer"
import { PageHeader } from "@/components/layout/PageHeader"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

export function IntegrationsPage() {
  return (
    <PageContainer>
      <PageHeader
        description="Revisa proveedores y puntos de salida que conectan Request Engine con la operacion."
        title="Integraciones"
      />
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between gap-3">
            <CardTitle>Proveedores</CardTitle>
            <Badge variant="neutral">MVP</Badge>
          </div>
        </CardHeader>
        <CardContent className="grid gap-3 text-sm sm:grid-cols-2">
          <div className="rounded-md bg-muted p-3">
            <PlugZap className="mb-2 h-4 w-4 text-primary" aria-hidden="true" />
            <p className="font-medium">Proveedor interno</p>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              Flujo por defecto para validar solicitudes antes de conectar automatizaciones externas.
            </p>
          </div>
          <div className="rounded-md border border-dashed p-3">
            <p className="font-medium">Webhook n8n</p>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              La configuracion del webhook vivira aqui cuando se active la integracion.
            </p>
          </div>
        </CardContent>
      </Card>
    </PageContainer>
  )
}
