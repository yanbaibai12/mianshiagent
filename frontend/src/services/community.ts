import api from './api'

export interface AgentQuestionBankItem {
  id: string
  section: string
  difficulty: string
  roles: string[]
  skills: string[]
  question: string
  concise_answer: string
  deep_dive_answer: string | null
  focus: string
  scenario: string
  answer_points: string[]
  followups: string[]
  scoring: string[]
  red_flags: string[]
  keywords: string[]
  tags: string[]
  source_title: string
  source_version: string
  practice_state: AgentQuestionPracticeState | null
}

export interface AgentQuestionPracticeState {
  question_id: string
  mastery_status: 'unseen' | 'known' | 'unknown' | 'review'
  is_favorite: boolean
  is_wrong: boolean
  review_count: number
  known_count: number
  wrong_count: number
  next_review_at: string | null
  last_practiced_at: string | null
  updated_at: string
}

export interface AgentQuestionPracticeUpdate {
  mastery_status?: 'unseen' | 'known' | 'unknown' | 'review'
  is_favorite?: boolean
  is_wrong?: boolean
  next_review_at?: string | null
}

export interface TrainingProfileDimension {
  dimension_key: string
  dimension_label: string
  mastery_score: number
  exposure_count: number
  known_count: number
  weak_count: number
  low_score_count: number
  last_signal: string | null
  last_source: string | null
  last_practiced_at: string | null
  updated_at: string | null
}

export interface TrainingProfile {
  dimensions: TrainingProfileDimension[]
  weakest_dimensions: TrainingProfileDimension[]
  stats: {
    practice_count?: number
    favorite_count?: number
    wrong_count?: number
    due_count?: number
  }
}

export interface AgentQuestionBankList {
  items: AgentQuestionBankItem[]
  total: number
  limit: number
  offset: number
  filters: {
    sections: string[]
    difficulties: string[]
    roles: string[]
    skills: string[]
  }
}

export interface InterviewExperienceShare {
  id: string
  organization_id: string | null
  company: string
  position: string
  city: string | null
  interview_date: string | null
  rounds: string | null
  difficulty: 'easy' | 'medium' | 'hard' | 'unknown'
  result: 'offer' | 'passed' | 'failed' | 'pending' | 'unknown'
  tags: string[]
  questions: string[]
  process: string | null
  content: string
  visibility: 'public' | 'organization' | 'private'
  is_anonymous: boolean
  allow_profile_usage: boolean
  status: string
  view_count: number
  like_count: number
  author_label: string
  can_edit: boolean
  created_at: string
  updated_at: string
}

export interface InterviewExperienceList {
  items: InterviewExperienceShare[]
  total: number
  limit: number
  offset: number
}

export interface InterviewExperienceCreatePayload {
  company: string
  position: string
  city?: string | null
  interview_date?: string | null
  rounds?: string | null
  difficulty: 'easy' | 'medium' | 'hard' | 'unknown'
  result: 'offer' | 'passed' | 'failed' | 'pending' | 'unknown'
  tags: string[]
  questions: string[]
  process?: string | null
  content: string
  visibility: 'public' | 'organization' | 'private'
  is_anonymous: boolean
  allow_profile_usage: boolean
}

export const communityApi = {
  listAgentQuestions: (params: {
    q?: string
    section?: string
    difficulty?: string
    role?: string
    skill?: string
    practice_filter?: 'favorite' | 'wrong' | 'due' | 'unseen'
    limit?: number
    offset?: number
  } = {}) => api.get<AgentQuestionBankList>('/api/community/agent-questions', { params }),
  getAgentQuestion: (questionId: string) =>
    api.get<AgentQuestionBankItem>(`/api/community/agent-questions/${questionId}`),
  updateAgentQuestionPractice: (questionId: string, payload: AgentQuestionPracticeUpdate) =>
    api.put<AgentQuestionPracticeState>(`/api/community/agent-questions/${questionId}/practice`, payload),
  trainingProfile: () => api.get<TrainingProfile>('/api/community/training-profile'),
  listExperiences: (params: {
    q?: string
    company?: string
    tag?: string
    difficulty?: string
    result?: string
    limit?: number
    offset?: number
  } = {}) => api.get<InterviewExperienceList>('/api/community/experiences', { params }),
  createExperience: (payload: InterviewExperienceCreatePayload) =>
    api.post<InterviewExperienceShare>('/api/community/experiences', payload),
  getExperience: (experienceId: string) =>
    api.get<InterviewExperienceShare>(`/api/community/experiences/${experienceId}`),
  likeExperience: (experienceId: string) =>
    api.post<InterviewExperienceShare>(`/api/community/experiences/${experienceId}/like`),
  deleteExperience: (experienceId: string) =>
    api.delete<{ message: string }>(`/api/community/experiences/${experienceId}`),
}
