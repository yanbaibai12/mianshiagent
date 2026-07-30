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
    resume_chunk_count: number
    vector_store?: {
      enabled: boolean
      backend: string
      collection: string
      resume_collection?: string
      configured_vector_size: number
      document_count: number | null
      chunk_count: number | null
      resume_chunk_count?: number | null
      available: boolean
      points_count: number
      resume_points_count?: number
      actual_vector_size: number | null
      resume_actual_vector_size?: number | null
      last_error: string | null
      embedding: {
        provider: string
        model: string
        vector_size: number
        base_url_configured: boolean
        device: string
        model_loaded: boolean
        allow_fallback: boolean
      }
    }
    rerank?: {
      enabled: boolean
      provider: string
      model: string
      top_k?: number
      batch_size?: number
      max_length?: number
      base_url_configured: boolean
      device: string
      allow_fallback: boolean
      model_loaded: boolean
      last_call?: Record<string, any>
    }
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
    task_queue?: {
      runtime: {
        backend: string
        queue_name: string
        redis_configured: boolean
        local_fallback_allowed: boolean
        available: boolean
        error?: string
      }
      status_counts: Record<string, number>
      backend_counts: Record<string, number>
      avg_queue_wait_ms: number
      avg_execution_ms: number
      recent_errors: Array<{
        id: string
        task_type: string
        resource_type: string | null
        resource_id: string | null
        error_type: string | null
        error_message: string
        updated_at: string
      }>
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

export interface ResumeReindexAllResult {
  status: string
  resume_count: number
  processed_count: number
  skipped_count: number
  chunk_count: number
  indexed_count: number
  failed_count: number
  collection: string
  items: Array<{
    resume_id: string
    title: string
    status: string
    chunk_count: number
    vector_status?: string
    vector_error?: string | null
  }>
}

export const systemApi = {
  status: () => api.get<SystemStatus>('/api/system/status'),
  releaseChecks: () => api.get<ReleaseChecks>('/api/system/release-checks'),
  rerankProbe: (query: string, documents: string[]) =>
    api.post('/api/system/rerank/probe', { query, documents }),
  adminBackup: () => api.post<{ filename: string; path: string; size_bytes: number; created_at: string }>('/api/system/admin/backup'),
  adminReindexResumes: (payload: { only_missing?: boolean; limit?: number | null } = {}) =>
    api.post<ResumeReindexAllResult>('/api/system/admin/reindex-resumes', payload),
}
