import api from './api'

export interface JobApplication {
  id: string
  organization_id: string | null
  resume_id: string | null
  current_resume_version_id: string | null
  company: string
  title: string
  jd_text: string
  status: string
  match_score: number | null
  ats_report: Record<string, any> | null
  interview_id: string | null
  created_at: string
  updated_at: string
}

export interface JobCreatePayload {
  title: string
  company?: string
  jd_text: string
  resume_id?: string | null
}

export const jobsApi = {
  list: () => api.get<JobApplication[]>('/api/jobs'),
  get: (id: string) => api.get<JobApplication>(`/api/jobs/${id}`),
  create: (payload: JobCreatePayload) => api.post<JobApplication>('/api/jobs', payload),
  update: (id: string, payload: Partial<JobCreatePayload> & { status?: string }) =>
    api.put<JobApplication>(`/api/jobs/${id}`, payload),
  delete: (id: string) => api.delete(`/api/jobs/${id}`),
  adaptResumeTask: (id: string) => api.post<{ task: any }>(`/api/jobs/${id}/adapt-resume-task`),
  createInterview: (id: string) => api.post<{ id: string }>(`/api/jobs/${id}/interview`),
  exportDeliveryResume: (id: string) =>
    api.get<Blob>(`/api/jobs/${id}/resume/export`, { responseType: 'blob' }),
}
