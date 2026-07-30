import api from './api'

export interface QualityAnnotation {
  id: string
  organization_id: string | null
  target_type: string
  target_id: string
  score: number
  labels: string[]
  notes: string | null
  status: string
  reviewer_role: string
  annotation_metadata: Record<string, any> | null
  created_at: string
  updated_at: string | null
}

export interface QualitySummary {
  total: number
  avg_score: number
  score_distribution: Record<string, number>
  target_stats: Array<{ target_type: string; count: number; avg_score: number }>
  top_labels: Array<{ label: string; count: number }>
  recent: Array<{
    id: string
    email: string
    target_type: string
    target_id: string
    score: number
    labels: string[]
    notes: string
    status: string
    created_at: string
  }>
  eval_candidates: {
    total: number
    open: number
    accepted: number
    added_to_eval: number
    dismissed: number
    status_counts: Record<string, number>
    recent: Array<{
      id: string
      email: string
      annotation_id: string | null
      target_type: string
      target_id: string
      source_score: number
      priority: number
      labels: string[]
      issue_summary: string
      status: string
      created_at: string
    }>
  }
}

export interface QualityEvalCandidate {
  id: string
  organization_id: string | null
  annotation_id: string | null
  target_type: string
  target_id: string
  source_score: number
  priority: number
  labels: string[]
  issue_summary: string | null
  status: string
  candidate_metadata: Record<string, any> | null
  created_at: string
  updated_at: string | null
}

export const qualityApi = {
  createAnnotation: (payload: {
    target_type: string
    target_id: string
    score: number
    labels?: string[]
    notes?: string
    metadata?: Record<string, any>
  }) => api.post<QualityAnnotation>('/api/quality/annotations', payload),
  listAnnotations: (params: { target_type?: string; target_id?: string } = {}) =>
    api.get<QualityAnnotation[]>('/api/quality/annotations', { params }),
  adminSummary: (limit = 20) => api.get<QualitySummary>('/api/quality/admin/summary', { params: { limit } }),
  adminEvalCandidates: (params: { status?: string; limit?: number } = {}) =>
    api.get<QualityEvalCandidate[]>('/api/quality/admin/eval-candidates', { params }),
  updateEvalCandidateStatus: (candidateId: string, status: 'open' | 'accepted' | 'added_to_eval' | 'dismissed') =>
    api.post<QualityEvalCandidate>(`/api/quality/admin/eval-candidates/${candidateId}/status`, { status }),
}
