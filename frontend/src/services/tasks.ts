import api from './api'

export interface AsyncTask {
  id: string
  task_type: string
  status: 'queued' | 'running' | 'success' | 'failed' | 'retrying' | 'cancelled'
  progress: number
  stage: string
  resource_type: string | null
  resource_id: string | null
  result_payload: Record<string, any> | null
  error_type: string | null
  error_message: string | null
  retry_count: number
  max_retries: number
  queue_backend: string
  queue_name: string
  external_job_id: string | null
  cancel_requested: boolean
  enqueued_at: string | null
  last_heartbeat_at: string | null
  started_at: string | null
  ended_at: string | null
  created_at: string
  updated_at: string
}

export const taskApi = {
  get: (id: string) => api.get<AsyncTask>(`/api/tasks/${id}`),
  list: () => api.get<AsyncTask[]>('/api/tasks'),
  retry: (id: string) => api.post<AsyncTask>(`/api/tasks/${id}/retry`),
  cancel: (id: string) => api.post<AsyncTask>(`/api/tasks/${id}/cancel`),
}
