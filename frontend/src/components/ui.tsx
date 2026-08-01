import { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from 'react'
import { Inbox } from 'lucide-react'

export function cn(...values: Array<string | false | null | undefined>) {
  return values.filter(Boolean).join(' ')
}

const buttonVariantClasses = {
  primary: 'btn-primary',
  secondary: 'btn-secondary',
  ghost: 'btn-ghost',
  danger: 'btn-danger',
  success: 'btn-success',
} as const

const badgeToneClasses = {
  neutral: 'badge-neutral',
  success: 'badge-success',
  warning: 'badge-warning',
  danger: 'badge-danger',
  info: 'badge-info',
} as const

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
        buttonVariantClasses[variant],
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
  className,
}: {
  children: ReactNode
  tone?: 'neutral' | 'success' | 'warning' | 'danger' | 'info'
  className?: string
}) {
  return <span className={cn('badge', badgeToneClasses[tone], className)}>{children}</span>
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
  icon,
}: {
  title: string
  description?: string
  action?: ReactNode
  icon?: ReactNode
}) {
  return (
    <div className="empty-state">
      <div className="empty-icon">{icon || <Inbox size={20} />}</div>
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
