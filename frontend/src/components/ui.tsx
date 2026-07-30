import { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from 'react'

export function cn(...values: Array<string | false | null | undefined>) {
  return values.filter(Boolean).join(' ')
}

export function Button({
  children,
  variant = 'primary',
  size = 'md',
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger' | 'success'
  size?: 'sm' | 'md' | 'lg'
}) {
  return (
    <button
      {...props}
      className={cn(
        'btn',
        `btn-${variant}`,
        size === 'sm' && 'btn-sm',
        size === 'lg' && 'btn-lg',
        className,
      )}
    >
      {children}
    </button>
  )
}

export function Card({
  children,
  className,
  ...props
}: HTMLAttributes<HTMLElement> & {
  children: ReactNode
  className?: string
}) {
  return <section {...props} className={cn('card', className)}>{children}</section>
}

export function Badge({
  children,
  tone = 'neutral',
}: {
  children: ReactNode
  tone?: 'neutral' | 'success' | 'warning' | 'danger' | 'info'
}) {
  return <span className={cn('badge', `badge-${tone}`)}>{children}</span>
}

export function Field({
  label,
  children,
  hint,
}: {
  label: string
  children: ReactNode
  hint?: string
}) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      {children}
      {hint && <span className="field-hint">{hint}</span>}
    </label>
  )
}

export function StatTile({
  label,
  value,
  meta,
  icon,
}: {
  label: string
  value: ReactNode
  meta?: ReactNode
  icon?: ReactNode
}) {
  return (
    <div className="stat-tile">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="stat-label">{label}</div>
          <div className="stat-value">{value}</div>
        </div>
        {icon && <div className="stat-icon">{icon}</div>}
      </div>
      {meta && <div className="stat-meta">{meta}</div>}
    </div>
  )
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string
  description?: string
  action?: ReactNode
}) {
  return (
    <div className="empty-state">
      <div className="empty-title">{title}</div>
      {description && <div className="empty-description">{description}</div>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}

export function LoadingState({ label = '加载中...' }: { label?: string }) {
  return (
    <div className="app-bg flex min-h-screen items-center justify-center p-6">
      <div className="loading-box">
        <div className="loading-dot" />
        <span>{label}</span>
      </div>
    </div>
  )
}

export function ProgressBar({ value }: { value: number }) {
  const safeValue = Math.max(0, Math.min(100, value))
  return (
    <div className="progress-track">
      <div className="progress-fill" style={{ width: `${safeValue}%` }} />
    </div>
  )
}
