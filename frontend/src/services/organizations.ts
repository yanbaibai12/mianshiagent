import api from './api'

export interface Organization {
  id: string
  name: string
  slug: string
  plan: string
  status: string
  role: 'owner' | 'admin' | 'member'
  created_at: string
}

export interface OrganizationMember {
  id: string
  user_id: string
  email: string
  nickname: string | null
  role: 'owner' | 'admin' | 'member'
  status: string
  created_at: string
}

export const organizationApi = {
  list: () => api.get<{ organizations: Organization[] }>('/api/organizations'),
  create: (name: string) => api.post<Organization>('/api/organizations', { name }),
  members: (organizationId: string) => api.get<OrganizationMember[]>(`/api/organizations/${organizationId}/members`),
  inviteMember: (organizationId: string, payload: { email: string; role: 'admin' | 'member' }) =>
    api.post<OrganizationMember>(`/api/organizations/${organizationId}/members`, payload),
}
