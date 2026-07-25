import api from './api'

export interface KnowledgeStats {
  document_count: number
  chunk_count: number
  categories: string[]
}

export interface KnowledgeSearchResult {
  document_id: string
  chunk_id: string
  title: string
  category: string
  source: string
  tags: string[]
  keywords: string[]
  content: string
  score: number
}

export const knowledgeApi = {
  stats: () => api.get<KnowledgeStats>('/api/knowledge/stats'),
  search: (query: string, categories?: string[], limit = 5) =>
    api.post<{ results: KnowledgeSearchResult[] }>('/api/knowledge/search', {
      query,
      categories,
      limit,
    }),
}
