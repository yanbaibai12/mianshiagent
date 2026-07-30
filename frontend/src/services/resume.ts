import api from './api'

export interface Resume {
  id: string
  title: string
  original_file: string | null
  original_text: string | null
  parsed_data: any
  optimized_data: any
  jd_text: string | null
  match_score: number | null
  template_id: string | null
  is_default: boolean
  created_at: string
  updated_at: string
}

export interface ResumeSummary {
  id: string
  title: string
  match_score: number | null
  template_id: string | null
  is_default: boolean
  created_at: string
  updated_at: string
}

export interface ResumeChunk {
  id: string
  resume_id: string
  section: string
  item_title: string
  chunk_index: number
  content: string
  keywords: string[] | null
  embedding_status: string
  created_at: string
}

export interface AtsDimension {
  key: string
  name: string
  score: number
  covered: string[]
  missing: string[]
  evidence: Array<{
    requirement?: string
    section?: string
    section_label?: string
    item_title?: string
    excerpt?: string
    score?: number
    source?: string
  }>
  risk: string[]
  suggestion: string
}

export interface AtsReport {
  total_score: number
  jd_requirements: Record<string, any>
  dimensions: AtsDimension[]
  requirement_evidence: AtsDimension['evidence']
  missing_top: string[]
  delivery_advice: string[]
  pipeline: Record<string, string>
}

export interface ResumeAdaptJDResult {
  jd_requirements: Record<string, any>
  match_score: number
  weak_points: string[]
  optimized_resume: Record<string, any>
  rag_references: Array<Record<string, any>>
  ats_report: AtsReport
  resume_evidence: AtsDimension['evidence']
}

export interface ResumeVersion {
  id: string
  resume_id: string
  version_number: number
  version_type: string
  title: string
  jd_text: string | null
  data: Record<string, any>
  ats_report: Record<string, any> | null
  change_details: any[] | null
  parent_version_id: string | null
  source_task_id: string | null
  source_job_id: string | null
  is_current: boolean
  status: string
  created_by: string
  notes: string | null
  created_at: string
}

export const resumeApi = {
  list: () => api.get<ResumeSummary[]>('/api/resumes'),
  get: (id: string) => api.get<Resume>(`/api/resumes/${id}`),
  chunks: (id: string) => api.get<ResumeChunk[]>(`/api/resumes/${id}/chunks`),
  reindex: (id: string) => api.post(`/api/resumes/${id}/reindex`),
  retrieveEvidence: (id: string, jdText: string) =>
    api.post(`/api/resumes/${id}/retrieve-evidence`, { jd_text: jdText }),
  versions: (id: string) => api.get<ResumeVersion[]>(`/api/resumes/${id}/versions`),
  createDeliveryVersion: (id: string) =>
    api.post<ResumeVersion>(`/api/resumes/${id}/versions/delivery`),
  rollbackVersion: (id: string, versionId: string) =>
    api.post<Resume>(`/api/resumes/${id}/versions/${versionId}/rollback`),
  exportDocx: (id: string, params?: { variant?: string; version_id?: string }) =>
    api.get<Blob>(`/api/resumes/${id}/export`, { params, responseType: 'blob' }),
  upload: (payload: FormData | { title: string; text: string }) => {
    if (payload instanceof FormData) {
      return api.post<Resume>('/api/resumes/upload', payload, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
    }
    return api.post<Resume>('/api/resumes/upload', payload)
  },
  update: (id: string, data: Partial<Resume>) =>
    api.put<Resume>(`/api/resumes/${id}`, data),
  delete: (id: string) => api.delete(`/api/resumes/${id}`),
  optimize: (id: string, templateId: string) =>
    api.post<Resume>(`/api/resumes/${id}/optimize`, { template_id: templateId }),
  adaptJD: (id: string, jdText: string) =>
    api.post<{ task: any }>(`/api/resumes/${id}/adapt-jd`, { jd_text: jdText }),
  adaptJDTask: (id: string, jdText: string) =>
    api.post<{ task: any }>(`/api/resumes/${id}/adapt-jd-task`, { jd_text: jdText }),
}
