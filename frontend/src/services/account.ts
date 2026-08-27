import api from './api'

export interface AccountExportData {
  exported_at: string
  user: {
    id: string
    email: string
    nickname: string | null
    created_at: string
    updated_at: string
  }
  /** Legacy export-only data retained until the Phase 1B contract migration. */
  billing_account: {
    plan: string
    status: string
    source: string
    expires_at: string | null
    notes: string | null
    created_at: string
    updated_at: string
  } | null
  resumes: Array<Record<string, unknown>>
  interviews: Array<Record<string, unknown>>
  usage_records: Array<Record<string, unknown>>
  /** Legacy export-only data retained for portability; not an active product surface. */
  organizations: Array<Record<string, unknown>>
  /** Legacy export-only payment history; never render as a plan or checkout capability. */
  payment_orders: Array<Record<string, unknown>>
  audit_logs: Array<Record<string, unknown>>
}

export const accountApi = {
  exportData: () => api.get<AccountExportData>('/api/account/export'),
  deleteAccount: () => api.delete<{ message: string }>('/api/account/delete'),
}
