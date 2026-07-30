import api from './api'

export interface KnowledgeStats {
  document_count: number
  chunk_count: number
  categories: string[]
  vector_store?: Record<string, unknown>
}

export interface KnowledgeSearchResult {
  document_id: string
  chunk_id: string
  title: string
  category: string
  source: string
  tags: string[]
  keywords: string[]
  metadata?: Record<string, unknown>
  content: string
  score: number
}

export interface InterviewBankImportResult {
  source: string
  version: string
  documents: number
  questions: number
  chunks: number
  duplicates_removed: number
  path: string
  vector_sync?: {
    status?: string
    collection?: string
    points_count?: number
    synced_count?: number
    error?: string
  } | null
}

export const knowledgeApi = {
  stats: () => api.get<KnowledgeStats>('/api/knowledge/stats'),
  search: (query: string, categories?: string[], limit = 5) =>
    api.post<{ results: KnowledgeSearchResult[] }>('/api/knowledge/search', {
      query,
      categories,
      limit,
    }),
  adminImportInterviewBank: (payload: { path?: string | null; skip_vector?: boolean; recreate_vector?: boolean } = {}) =>
    api.post<InterviewBankImportResult>('/api/knowledge/admin/import-interview-bank', payload),
}
