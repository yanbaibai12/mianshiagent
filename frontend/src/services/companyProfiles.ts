import api from './api'

export interface CompanyProfileRound {
  round_type: string
  name: string
  occurrence_count: number
  source_count: number
}

export interface CompanyProfileQuestion {
  canonical_question: string
  sample_question: string
  occurrence_count: number
  round_type: string
  topics: string[]
  difficulty: string
  source_count: number
}

export interface CompanyProfileTopic {
  topic_key: string
  name: string
  occurrence_count: number
  source_count: number
}

export interface CompanyInterviewProfile {
  id: string
  organization_id: string | null
  scope: 'public' | 'organization'
  company_name: string
  normalized_company_name: string
  position_name: string
  normalized_position_name: string
  common_rounds: CompanyProfileRound[]
  frequent_questions: CompanyProfileQuestion[]
  technical_topics: CompanyProfileTopic[]
  difficulty_distribution: Record<string, number>
  interview_count: number
  source_experience_ids: string[] | null
  profile_confidence: 'low' | 'medium' | 'high'
  first_observed_at: string | null
  last_observed_at: string | null
  generated_at: string | null
  updated_at: string | null
  profile_version: number
}

export interface CompanyProfileList {
  items: CompanyInterviewProfile[]
  total: number
  limit: number
  offset: number
}

export const companyProfileApi = {
  list: (params: {
    company?: string
    position?: string
    round_type?: string
    topic?: string
    limit?: number
    offset?: number
  } = {}) => api.get<CompanyProfileList>('/api/company-profiles', { params }),
  get: (profileId: string) => api.get<CompanyInterviewProfile>(`/api/company-profiles/${profileId}`),
}
