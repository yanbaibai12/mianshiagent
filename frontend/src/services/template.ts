import api from './api'

export interface ResumeTemplate {
  id: string
  name: string
  category: string | null
  structure: any
  is_builtin: boolean
}

export const templateApi = {
  list: () => api.get<ResumeTemplate[]>('/api/templates'),
  get: (id: string) => api.get<ResumeTemplate>(`/api/templates/${id}`),
}
