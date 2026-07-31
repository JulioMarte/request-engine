import { Plus } from "lucide-react"
import { EmptyState } from "@/components/common/EmptyState"
import { Field } from "@/components/common/Field"
import { PageContainer } from "@/components/layout/PageContainer"
import { PageHeader } from "@/components/layout/PageHeader"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"

export function CatalogPage() {
  return (
    <PageContainer>
      <PageHeader
        description="Define los servicios o productos que la IA puede reconocer y convertir en solicitudes."
        title="Catalogo"
      />
      <Card className="mb-4">
        <CardHeader>
          <CardTitle>Nuevo item</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
          <Field htmlFor="catalog-name" label="Nombre">
            <Input id="catalog-name" placeholder="Ej. Consulta inicial" />
          </Field>
          <Field htmlFor="catalog-fulfillment" label="Tipo de cumplimiento">
            <Input id="catalog-fulfillment" placeholder="Ej. cita, cotizacion" />
          </Field>
          <Button>
            <Plus className="h-4 w-4" aria-hidden="true" />
            Agregar
          </Button>
        </CardContent>
      </Card>
      <EmptyState
        title="Catalogo sin items"
        description="Agrega servicios para que las conversaciones puedan mapearse a solicitudes concretas."
      />
    </PageContainer>
  )
}
