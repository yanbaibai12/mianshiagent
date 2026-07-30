import api from './api'

export interface Interview {
  id: string
  resume_id: string | null
  jd_text: string | null
  status: string
  total_score: number | null
  dimension_scores: any
  summary: string | null
  weak_points: string[] | null
  suggestions: string[] | null
  created_at: string
  updated_at: string
}

export interface InterviewQuestion {
  id: string
  resume_point_id: string | null
  point_title: string | null
  module: string
  source_section: string | null
  question_type: string
  sequence: number
  question: string
  user_answer: string | null
  scores: any
  total_score: number | null
  feedback: string | null
  refined_answer: string | null
  answered_at: string | null
}

export interface InterviewReport extends Interview {
  questions: InterviewQuestion[]
}

export const interviewApi = {
  list: () => api.get<Interview[]>('/api/interviews'),
  get: (id: string) => api.get<Interview>(`/api/interviews/${id}`),
  create: (resumeId: string, jdText?: string) =>
    api.post<Interview>('/api/interviews', { resume_id: resumeId, jd_text: jdText }),
  generateQuestions: (id: string, force = false) =>
    api.post(`/api/interviews/${id}/generate-questions`, null, {
      params: force ? { force: true } : undefined,
    }),
  regenerateQuestion: (id: string, questionId: string) =>
    api.post<InterviewQuestion>(`/api/interviews/${id}/regenerate-question`, null, {
      params: { question_id: questionId },
    }),
  listQuestions: (id: string) =>
    api.get<InterviewQuestion[]>(`/api/interviews/${id}/questions`),
  submitAnswer: (interviewId: string, questionId: string, answer: string) =>
    api.post<InterviewQuestion>(`/api/interviews/${interviewId}/questions/${questionId}/answer`, { answer }),
  finish: (id: string) => api.post<InterviewReport>(`/api/interviews/${id}/finish`),
  getReport: (id: string) => api.get<InterviewReport>(`/api/interviews/${id}/report`),
  exportReport: (id: string) =>
    api.get<{ filename: string; content: string }>(`/api/interviews/${id}/report/export`),
  exportReportFile: (id: string, format: 'docx' | 'pdf') =>
    api.get<Blob>(`/api/interviews/${id}/report/export`, { params: { format }, responseType: 'blob' }),
  delete: (id: string) => api.delete(`/api/interviews/${id}`),
}
