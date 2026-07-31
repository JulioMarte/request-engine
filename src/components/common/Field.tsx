import type { ReactNode } from "react"

export function Field({
  children,
  description,
  htmlFor,
  label,
}: {
  children: ReactNode
  description?: string
  htmlFor: string
  label: string
}) {
  return (
    <div className="space-y-1.5">
      <label className="text-xs font-medium text-foreground" htmlFor={htmlFor}>
        {label}
      </label>
      {children}
      {description && <p className="text-xs leading-5 text-muted-foreground">{description}</p>}
    </div>
  )
}
