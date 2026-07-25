import api from './api'

export interface User {
  id: string
  email: string
  nickname: string | null
}

export const authApi = {
  register: (email: string, password: string, nickname?: string) =>
    api.post('/api/auth/register', { email, password, nickname }),
  login: (email: string, password: string) =>
    api.post('/api/auth/login', { email, password }),
  me: () => api.get('/api/auth/me'),
}
