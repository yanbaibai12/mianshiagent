import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router'
import { ArrowLeft, Building2, RefreshCw, UserPlus, UsersRound } from 'lucide-react'
import AppShell from '../components/AppShell'
import { Badge, Button, Card, EmptyState, Field, LoadingState, StatTile } from '../components/ui'
import { organizationApi, Organization, OrganizationMember } from '../services/organizations'

function roleTone(role: string): 'neutral' | 'success' | 'warning' | 'danger' | 'info' {
  if (role === 'owner') return 'success'
  if (role === 'admin') return 'info'
  return 'neutral'
}

export default function OrganizationSettingsPage() {
  const navigate = useNavigate()
  const [organizations, setOrganizations] = useState<Organization[]>([])
  const [selectedOrgId, setSelectedOrgId] = useState('')
  const [members, setMembers] = useState<OrganizationMember[]>([])
  const [newOrgName, setNewOrgName] = useState('')
  const [inviteEmail, setInviteEmail] = useState('')
  const [inviteRole, setInviteRole] = useState<'admin' | 'member'>('member')
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  const selectedOrg = useMemo(
    () => organizations.find((item) => item.id === selectedOrgId) || organizations[0],
    [organizations, selectedOrgId],
  )
  const canManage = selectedOrg?.role === 'owner' || selectedOrg?.role === 'admin'

  useEffect(() => {
    loadOrganizations()
  }, [])

  const loadOrganizations = async () => {
    setLoading(true)
    setError('')
    try {
      const res = await organizationApi.list()
      setOrganizations(res.data.organizations)
      const nextOrg = res.data.organizations.find((item) => item.id === selectedOrgId) || res.data.organizations[0]
      setSelectedOrgId(nextOrg?.id || '')
      if (nextOrg) {
        const membersRes = await organizationApi.members(nextOrg.id)
        setMembers(membersRes.data)
      } else {
        setMembers([])
      }
    } catch (err: any) {
      setError(err.response?.data?.detail || '组织数据加载失败')
    } finally {
      setLoading(false)
    }
  }

  const loadMembers = async (organizationId: string) => {
    setSelectedOrgId(organizationId)
    setError('')
    try {
      const res = await organizationApi.members(organizationId)
      setMembers(res.data)
    } catch (err: any) {
      setMembers([])
      setError(err.response?.data?.detail || '成员列表加载失败')
    }
  }

  const handleCreateOrg = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!newOrgName.trim()) return
    setSubmitting(true)
    setError('')
    setMessage('')
    try {
      const res = await organizationApi.create(newOrgName.trim())
      setMessage(`已创建组织：${res.data.name}`)
      setNewOrgName('')
      await loadOrganizations()
      await loadMembers(res.data.id)
    } catch (err: any) {
      setError(err.response?.data?.detail || '创建组织失败')
    } finally {
      setSubmitting(false)
    }
  }

  const handleInvite = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!selectedOrg || !inviteEmail.trim()) return
    setSubmitting(true)
    setError('')
    setMessage('')
    try {
      const res = await organizationApi.inviteMember(selectedOrg.id, {
        email: inviteEmail.trim(),
        role: inviteRole,
      })
      setMessage(`已添加成员：${res.data.email}`)
      setInviteEmail('')
      await loadMembers(selectedOrg.id)
    } catch (err: any) {
      setError(err.response?.data?.detail || '添加成员失败')
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) return <LoadingState label="正在加载组织" />

  return (
    <AppShell
      title="组织管理"
      description="管理团队空间、成员角色和组织级协作边界。"
      actions={
        <Button type="button" variant="secondary" onClick={() => navigate('/resumes')}>
          <ArrowLeft size={16} />
          返回工作台
        </Button>
      }
    >
      <div className="space-y-6">
        {error && <div className="rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div>}
        {message && <div className="rounded-md border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{message}</div>}

        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <StatTile label="组织数量" value={organizations.length} meta="当前账号可访问" icon={<Building2 size={18} />} />
          <StatTile label="当前组织" value={selectedOrg?.name || '-'} meta={selectedOrg?.slug || '-'} icon={<UsersRound size={18} />} />
          <StatTile label="成员数量" value={members.length} meta={canManage ? '可管理成员' : '只读成员'} icon={<UserPlus size={18} />} />
        </div>

        <div className="grid grid-cols-1 gap-6 xl:grid-cols-[360px_minmax(0,1fr)_380px]">
          <Card>
            <div className="mb-5 flex items-start justify-between gap-4">
              <div>
                <h2 className="card-title">组织空间</h2>
                <p className="card-subtitle">切换后可查看该组织成员。</p>
              </div>
              <Button type="button" variant="ghost" size="sm" onClick={loadOrganizations}>
                <RefreshCw size={14} />
              </Button>
            </div>
            <div className="space-y-3">
              {organizations.map((org) => (
                <button
                  type="button"
                  key={org.id}
                  onClick={() => loadMembers(org.id)}
                  className={`w-full rounded-lg border p-4 text-left transition ${selectedOrg?.id === org.id ? 'border-cyan-200 bg-cyan-50' : 'border-slate-200 bg-white hover:border-cyan-200'}`}
                >
                  <div className="flex items-center justify-between gap-3">
                    <div className="min-w-0">
                      <div className="truncate font-semibold text-slate-950">{org.name}</div>
                      <div className="mt-1 truncate text-xs text-slate-500">{org.slug}</div>
                    </div>
                    <Badge tone={roleTone(org.role)}>{org.role}</Badge>
                  </div>
                </button>
              ))}
              {organizations.length === 0 && <EmptyState title="暂无组织" />}
            </div>
          </Card>

          <Card>
            <div className="mb-5">
              <h2 className="card-title">成员列表</h2>
              <p className="card-subtitle">owner/admin 可添加成员并调整成员角色。</p>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[620px] text-left text-sm">
                <thead>
                  <tr className="border-b border-slate-200 text-xs font-semibold uppercase tracking-normal text-slate-500">
                    <th className="px-3 py-3">成员</th>
                    <th className="px-3 py-3">角色</th>
                    <th className="px-3 py-3">状态</th>
                    <th className="px-3 py-3">加入时间</th>
                  </tr>
                </thead>
                <tbody>
                  {members.map((member) => (
                    <tr key={member.id} className="border-b border-slate-100">
                      <td className="px-3 py-3">
                        <div className="font-semibold text-slate-950">{member.nickname || member.email}</div>
                        <div className="mt-1 text-xs text-slate-500">{member.email}</div>
                      </td>
                      <td className="px-3 py-3"><Badge tone={roleTone(member.role)}>{member.role}</Badge></td>
                      <td className="px-3 py-3 text-slate-600">{member.status}</td>
                      <td className="px-3 py-3 text-slate-600">{new Date(member.created_at).toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {members.length === 0 && <EmptyState title="暂无成员" />}
            </div>
          </Card>

          <div className="space-y-6">
            <Card>
              <div className="mb-5">
                <h2 className="card-title">创建组织</h2>
                <p className="card-subtitle">适合机构试点、团队训练和企业账号池。</p>
              </div>
              <form onSubmit={handleCreateOrg} className="space-y-4">
                <Field label="组织名称">
                  <input className="input" value={newOrgName} onChange={(event) => setNewOrgName(event.target.value)} maxLength={120} />
                </Field>
                <Button type="submit" className="w-full" disabled={submitting || !newOrgName.trim()}>
                  <Building2 size={16} />
                  创建组织
                </Button>
              </form>
            </Card>

            <Card>
              <div className="mb-5">
                <h2 className="card-title">添加成员</h2>
                <p className="card-subtitle">被添加的用户需要先完成注册。</p>
              </div>
              {selectedOrg ? (
                <form onSubmit={handleInvite} className="space-y-4">
                  <Field label="成员邮箱">
                    <input className="input" type="email" value={inviteEmail} onChange={(event) => setInviteEmail(event.target.value)} disabled={!canManage} />
                  </Field>
                  <Field label="角色">
                    <select className="select" value={inviteRole} onChange={(event) => setInviteRole(event.target.value as 'admin' | 'member')} disabled={!canManage}>
                      <option value="member">成员</option>
                      <option value="admin">管理员</option>
                    </select>
                  </Field>
                  <Button type="submit" className="w-full" disabled={submitting || !canManage || !inviteEmail.trim()}>
                    <UserPlus size={16} />
                    添加成员
                  </Button>
                </form>
              ) : (
                <EmptyState title="请先创建组织" />
              )}
            </Card>
          </div>
        </div>
      </div>
    </AppShell>
  )
}
