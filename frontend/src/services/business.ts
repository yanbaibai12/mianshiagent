import api from './api'

export interface BusinessEntitlements {
  plan: {
    current: string
    name: string
    status: string
    source: string
    expires_at: string | null
    billing_enabled: boolean
    payment_provider: string
    checkout_available: boolean
    upgrade_contact: string
  }
  usage: {
    resumes: number
    interviews: number
    resume_optimizations: number
    jd_adaptations: number
    report_exports: number
  }
  quotas: {
    free_resume_quota: number
    free_interview_quota: number
    free_optimize_quota: number
    free_jd_adapt_quota: number
    free_report_export_quota: number
    pro_resume_quota: number
    pro_interview_quota: number
    pro_optimize_quota: number
    pro_jd_adapt_quota: number
    pro_report_export_quota: number
    sprint_package_price_cny: number
  }
  features: Array<{
    key: string
    label: string
    used: number
    limit: number | null
    remaining: number | null
    enforced: boolean
    can_use: boolean
  }>
  entitlements: {
    can_create_resume: boolean
    can_create_interview: boolean
    can_optimize_resume: boolean
    can_adapt_jd: boolean
    can_export_report: boolean
    resume_remaining: number | null
    interview_remaining: number | null
    optimize_remaining: number | null
    jd_adapt_remaining: number | null
    report_export_remaining: number | null
    paywall_active: boolean
    locked_features: string[]
  }
  upgrade: {
    recommended_plan: string
    price_cny: number
    sprint_package_price_cny: number
    cta: string
  }
  plans: Array<{
    key: string
    name: string
    price_cny: number | null
    positioning: string
  }>
}

export interface UpgradeRequestResponse {
  message: string
  payment_provider: string
  upgrade_contact: string
  pro_monthly_price_cny: number
}

export interface AdminUsageSummary {
  window_days: number
  totals: {
    users: number
    resumes: number
    interviews: number
    billing_accounts: number
    usage_records: number
    llm_call_count: number
    estimated_input_tokens: number
    estimated_output_tokens: number
    estimated_cost_cny: number
  }
  by_feature: Array<{
    feature: string
    units: number
    record_count: number
    llm_call_count: number
    estimated_input_tokens: number
    estimated_output_tokens: number
    estimated_cost_cny: number
  }>
  upgrade_requests: Array<{
    id: string
    email: string
    feature: string
    units: number
    created_at: string
    estimated_cost_cny: number
    metadata: Record<string, unknown>
  }>
  recent_records: Array<{
    id: string
    email: string
    feature: string
    units: number
    created_at: string
    estimated_cost_cny: number
  }>
}

export interface GrantPlanResponse {
  message: string
  user_id: string
  plan: string
  status: string
  source: string
  expires_at: string | null
}

export const businessApi = {
  entitlements: () => api.get<BusinessEntitlements>('/api/business/entitlements'),
  requestUpgrade: () => api.post<UpgradeRequestResponse>('/api/business/upgrade-request'),
  adminUsageSummary: (days = 30, limit = 20) =>
    api.get<AdminUsageSummary>('/api/business/admin/usage-summary', { params: { days, limit } }),
  grantPlan: (payload: { email: string; plan: 'free' | 'pro' | 'enterprise'; days?: number; notes?: string }) =>
    api.post<GrantPlanResponse>('/api/business/admin/grant-plan', payload),
}
