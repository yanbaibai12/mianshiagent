import api from './api'

export interface AuditLog {
  id: string
  actor_user_id: string | null
  actor_email: string | null
  target_user_id: string | null
  organization_id: string | null
  event_type: string
  resource_type: string
  resource_id: string | null
  ip_address: string | null
  user_agent: string | null
  metadata: Record<string, unknown>
  created_at: string
}

export const auditApi = {
  adminLogs: (params: { limit?: number; event_type?: string } = {}) =>
    api.get<{ logs: AuditLog[] }>('/api/audit/admin/logs', { params }),
}
