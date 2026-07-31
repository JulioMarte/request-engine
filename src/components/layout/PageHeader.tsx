import type { ReactNode } from "react"

export function PageHeader({
  actions,
  description,
  eyebrow,
  title,
}: {
  actions?: ReactNode
  description?: string
  eyebrow?: string
  title: string
}) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <div>
        {eyebrow && <p className="mb-1 text-xs font-medium uppercase text-primary">{eyebrow}</p>}
        <h1 className="text-xl font-semibold">{title}</h1>
        {description && <p className="mt-1 max-w-2xl text-sm leading-6 text-muted-foreground">{description}</p>}
      </div>
      {actions}
    </div>
  )
}
