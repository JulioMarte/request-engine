import { PageContainer } from "@/components/layout/PageContainer"
import { PageHeader } from "@/components/layout/PageHeader"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { AuthStatusCard } from "@/features/auth/components/AuthStatusCard"

const sections = [
  { title: "Tenants", description: "Configura negocios y cuentas de Chatwoot." },
  { title: "Canales", description: "Relaciona inboxes y origenes conversacionales." },
  { title: "Catalogo", description: "Organiza servicios y tipos de cumplimiento." },
  { title: "Conocimiento", description: "Mantiene respuestas reutilizables por tenant." },
  { title: "Integraciones", description: "Prepara proveedores internos y webhooks." },
]

export function AdminHomePage() {
  return (
    <PageContainer>
      <PageHeader
        description="Superficie interna para preparar datos, autenticacion e integraciones antes de activar flujos automaticos."
        title="Administracion"
      />
      <div className="mb-4">
        <AuthStatusCard />
      </div>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {sections.map((section) => (
          <Card key={section.title}>
            <CardHeader>
              <CardTitle>{section.title}</CardTitle>
            </CardHeader>
            <CardContent className="text-sm leading-6 text-muted-foreground">{section.description}</CardContent>
          </Card>
        ))}
      </div>
    </PageContainer>
  )
}
