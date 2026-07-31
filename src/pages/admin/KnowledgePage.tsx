import { Plus } from "lucide-react"
import { EmptyState } from "@/components/common/EmptyState"
import { Field } from "@/components/common/Field"
import { PageContainer } from "@/components/layout/PageContainer"
import { PageHeader } from "@/components/layout/PageHeader"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"

export function KnowledgePage() {
  return (
    <PageContainer>
      <PageHeader
        description="Carga respuestas y criterios que ayudan a mantener la IA alineada con la operacion."
        title="Conocimiento"
      />
      <Card className="mb-4">
        <CardHeader>
          <CardTitle>Nueva entrada</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 sm:grid-cols-[1fr_2fr_auto] sm:items-end">
          <Field htmlFor="knowledge-title" label="Titulo">
            <Input id="knowledge-title" placeholder="Ej. Politica de cancelacion" />
          </Field>
          <Field htmlFor="knowledge-answer" label="Respuesta">
            <Input id="knowledge-answer" placeholder="Resumen operativo reutilizable" />
          </Field>
          <Button>
            <Plus className="h-4 w-4" aria-hidden="true" />
            Agregar
          </Button>
        </CardContent>
      </Card>
      <EmptyState
        title="Sin conocimiento cargado"
        description="Las entradas apareceran aqui para que el equipo pueda revisar y mantener respuestas confiables."
      />
    </PageContainer>
  )
}
