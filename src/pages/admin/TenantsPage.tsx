import { Building2 } from "lucide-react"
import { EmptyState } from "@/components/common/EmptyState"
import { Field } from "@/components/common/Field"
import { PageContainer } from "@/components/layout/PageContainer"
import { PageHeader } from "@/components/layout/PageHeader"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"

export function TenantsPage() {
  return (
    <PageContainer>
      <PageHeader
        description="Registra negocios y vincula cada tenant con su cuenta de Chatwoot."
        title="Tenants"
      />
      <Card className="mb-4">
        <CardHeader>
          <CardTitle>Nuevo tenant</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
          <Field htmlFor="tenant-name" label="Nombre del negocio">
            <Input id="tenant-name" placeholder="Ej. Clinica Central" />
          </Field>
          <Field htmlFor="tenant-account" label="Cuenta Chatwoot">
            <Input id="tenant-account" inputMode="numeric" placeholder="Ej. 42" />
          </Field>
          <Button>
            <Building2 className="h-4 w-4" aria-hidden="true" />
            Crear
          </Button>
        </CardContent>
      </Card>
      <EmptyState
        title="Todavia no hay tenants"
        description="Cuando Convex tenga datos, aqui se mostraran los negocios disponibles para operar solicitudes."
      />
    </PageContainer>
  )
}
