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
  organizations: Array<Record<string, unknown>>
  payment_orders: Array<Record<string, unknown>>
  audit_logs: Array<Record<string, unknown>>
}

export const accountApi = {
  exportData: () => api.get<AccountExportData>('/api/account/export'),
  deleteAccount: () => api.delete<{ message: string }>('/api/account/delete'),
}
