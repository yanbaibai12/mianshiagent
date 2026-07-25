import api from './api'

export interface ReleaseCheck {
  key: string
  severity: 'pass' | 'warning' | 'critical'
  message: string
  recommendation: string
}

export interface ReleaseChecks {
  environment: string
  publishable: boolean
  critical_count: number
  warning_count: number
  checks: ReleaseCheck[]
}

export interface SystemStatus {
  app: string
  version: string
  environment: string
  public_base_url: string
  database: {
    ok: boolean
    driver: string
    error: string | null
  }
  llm: {
    provider: string
    model: string
    configured: boolean
    local_fallback: boolean
    fallback_allowed: boolean
  }
  rag: {
    enabled: boolean
    retriever: string
    document_count: number
    chunk_count: number
  }
  limits: {
    max_file_size_mb: number
    max_resume_text_length: number
    max_jd_text_length: number
    max_answer_length: number
  }
  security: {
    admin_enabled: boolean
    cors_origins: string[]
    trusted_hosts: string[]
    docs_enabled: boolean
    auto_create_db: boolean
    rate_limit_window_seconds: number
    auth_requests_per_window: number
    api_requests_per_window: number
  }
  business: {
    billing_enabled: boolean
    payment_provider: string
    upgrade_contact: string
    free_resume_quota: number
    free_interview_quota: number
    free_optimize_quota: number
    free_jd_adapt_quota: number
    free_report_export_quota: number
    pro_monthly_price_cny: number
    pro_resume_quota: number
    pro_interview_quota: number
    pro_optimize_quota: number
    pro_jd_adapt_quota: number
    pro_report_export_quota: number
    sprint_package_price_cny: number
  }
  operations: {
    metrics_enabled: boolean
    metrics: {
      uptime_seconds: number
      total_requests: number
      status_counts: Record<string, number>
      top_paths: Array<{ path: string; count: number }>
      avg_duration_ms: number
      p95_duration_ms: number
    }
    backup: {
      enabled: boolean
      backup_dir: string
      retention_days: number
      latest_backup: {
        filename: string
        size_bytes: number
        created_at: string
      } | null
      backup_count: number
      database_supported: boolean
    }
    release: {
      deployment_color: string
      release_channel: string
      canary_percent: number
    }
  }
  release: ReleaseChecks
}

export const systemApi = {
  status: () => api.get<SystemStatus>('/api/system/status'),
  releaseChecks: () => api.get<ReleaseChecks>('/api/system/release-checks'),
  adminBackup: () => api.post<{ filename: string; path: string; size_bytes: number; created_at: string }>('/api/system/admin/backup'),
}
