import api from './api'

export type TrainingTaskType =
  | 'agent_question'
  | 'wrong_review'
  | 'mock_interview'
  | 'experience_reading'
  | 'project_review'

export type TrainingTaskStatus = 'pending' | 'completed' | 'skipped'

export interface TrainingPlanTask {
  id: string
  task_type: TrainingTaskType
  title: string
  description: string
  scheduled_date: string
  estimated_minutes: number
  priority: number
  status: TrainingTaskStatus
  related_question_id?: string | null
  related_interview_id?: string | null
  related_experience_id?: string | null
  related_company_profile_id?: string | null
  target_dimensions: string[]
  recommendation_reason: string
  completed_at?: string | null
  created_at: string
  updated_at: string
}

export interface TrainingPlan {
  id: string
  organization_id: string
  source_interview_id?: string | null
  week_start: string
  week_end: string
  status: 'draft' | 'active' | 'completed'
  plan_summary: string
  estimated_minutes: number
  completion_rate: number
  generation_metadata: {
    weak_dimensions?: Array<{
      dimension_key: string
      dimension_label: string
      mastery_score: number
      weak_count: number
    }>
    target_company?: string | null
    daily_limit_minutes?: number
    [key: string]: unknown
  }
  tasks: TrainingPlanTask[]
  created_at: string
  updated_at: string
}

export const trainingPlanApi = {
  current: () => api.get<TrainingPlan>('/api/training-plans/current'),
  get: (id: string) => api.get<TrainingPlan>(`/api/training-plans/${id}`),
  generate: (sourceInterviewId?: string) =>
    api.post<TrainingPlan>('/api/training-plans/generate', {
      source_interview_id: sourceInterviewId || null,
    }),
  updateTask: (
    planId: string,
    taskId: string,
    update: { status?: TrainingTaskStatus; scheduled_date?: string },
  ) => api.patch<TrainingPlan>(`/api/training-plans/${planId}/tasks/${taskId}`, update),
  regenerate: (planId: string) =>
    api.post<TrainingPlan>(`/api/training-plans/${planId}/regenerate`),
}
