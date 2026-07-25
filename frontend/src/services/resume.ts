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

export const resumeApi = {
  list: () => api.get<ResumeSummary[]>('/api/resumes'),
  get: (id: string) => api.get<Resume>(`/api/resumes/${id}`),
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
    api.post<any>(`/api/resumes/${id}/adapt-jd`, { jd_text: jdText }),
}
