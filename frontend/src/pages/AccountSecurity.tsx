import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft, Download, FileText, ShieldCheck, Trash2, UserRound } from 'lucide-react'
import AppShell from '../components/AppShell'
import { Badge, Button, Card, Field, StatTile } from '../components/ui'
import { accountApi, AccountExportData } from '../services/account'
import { useAuthStore } from '../stores/auth'

function formatDate(value: string | null | undefined) {
  return value ? new Date(value).toLocaleString() : '-'
}

function downloadJson(filename: string, data: AccountExportData) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

export default function AccountSecurityPage() {
  const navigate = useNavigate()
  const user = useAuthStore((state) => state.user)
  const logout = useAuthStore((state) => state.logout)
  const [exportData, setExportData] = useState<AccountExportData | null>(null)
  const [confirmEmail, setConfirmEmail] = useState('')
  const [loadingExport, setLoadingExport] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  const canDelete = Boolean(user?.email && confirmEmail.trim().toLowerCase() === user.email.toLowerCase())

  const exportSummary = useMemo(() => {
    if (!exportData) return null
    return [
      { label: '简历', value: exportData.resumes.length },
      { label: '面试', value: exportData.interviews.length },
      { label: '用量', value: exportData.usage_records.length },
      { label: '审计', value: exportData.audit_logs.length },
    ]
  }, [exportData])

  const handleExport = async () => {
    setError('')
    setMessage('')
    setLoadingExport(true)
    try {
      const res = await accountApi.exportData()
      const data = res.data
      setExportData(data)
      downloadJson(`interview-agent-account-${new Date().toISOString().slice(0, 10)}.json`, data)
      setMessage('账号数据已导出')
    } catch (err: any) {
      setError(err.response?.data?.detail || '账号数据导出失败')
    } finally {
      setLoadingExport(false)
    }
  }

  const handleDelete = async () => {
    if (!canDelete) return
    setError('')
    setMessage('')
    setDeleting(true)
    try {
      await accountApi.deleteAccount()
      logout()
      navigate('/login')
    } catch (err: any) {
      setError(err.response?.data?.detail || '账号注销失败')
      setDeleting(false)
    }
  }

  return (
    <AppShell
      title="账号安全"
      description="账号数据、导出记录和注销操作集中管理。"
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

        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
          <StatTile label="当前账号" value={user?.nickname || '已登录'} meta={user?.email} icon={<UserRound size={18} />} />
          <StatTile label="最近导出" value={exportData ? formatDate(exportData.exported_at) : '-'} meta="JSON 数据包" icon={<Download size={18} />} />
          <StatTile label="简历资产" value={exportData?.resumes.length ?? '-'} meta="导出后刷新" icon={<FileText size={18} />} />
          <StatTile label="审计记录" value={exportData?.audit_logs.length ?? '-'} meta="当前账号相关事件" icon={<ShieldCheck size={18} />} />
        </div>

        <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_420px]">
          <Card>
            <div className="mb-5 flex items-start justify-between gap-4">
              <div>
                <h2 className="card-title">数据导出</h2>
                <p className="card-subtitle">导出账号、简历、面试、用量和审计记录。</p>
              </div>
              <Badge tone="info">Data Portability</Badge>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <Button type="button" onClick={handleExport} disabled={loadingExport}>
                <Download size={16} />
                {loadingExport ? '导出中...' : '导出 JSON'}
              </Button>
              {exportData && (
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => downloadJson(`interview-agent-account-${new Date().toISOString().slice(0, 10)}.json`, exportData)}
                >
                  <Download size={16} />
                  重新下载
                </Button>
              )}
            </div>

            {exportSummary && (
              <div className="mt-6 grid grid-cols-2 gap-3 md:grid-cols-4">
                {exportSummary.map((item) => (
                  <div key={item.label} className="rounded-md bg-slate-50 px-4 py-3">
                    <div className="text-xs font-semibold text-slate-500">{item.label}</div>
                    <div className="mt-1 text-xl font-bold text-slate-950">{item.value}</div>
                  </div>
                ))}
              </div>
            )}

            {exportData && (
              <div className="mt-6 overflow-hidden rounded-md border border-slate-200">
                <div className="grid grid-cols-1 divide-y divide-slate-200 text-sm md:grid-cols-2 md:divide-x md:divide-y-0">
                  <div className="p-4">
                    <div className="text-xs font-semibold text-slate-500">账号</div>
                    <div className="mt-1 font-semibold text-slate-950">{exportData.user.email}</div>
                    <div className="mt-1 text-slate-500">创建于 {formatDate(exportData.user.created_at)}</div>
                  </div>
                  <div className="p-4">
                    <div className="text-xs font-semibold text-slate-500">权益</div>
                    <div className="mt-1 font-semibold text-slate-950">{exportData.billing_account?.plan || 'free'}</div>
                    <div className="mt-1 text-slate-500">到期 {formatDate(exportData.billing_account?.expires_at)}</div>
                  </div>
                </div>
              </div>
            )}
          </Card>

          <Card className="border-rose-200">
            <div className="mb-5 flex items-start justify-between gap-4">
              <div>
                <h2 className="card-title">注销账号</h2>
                <p className="card-subtitle">删除账号及关联简历、面试、用量记录。</p>
              </div>
              <Trash2 size={18} className="text-rose-600" />
            </div>
            <div className="space-y-4">
              <div className="rounded-md border border-rose-200 bg-rose-50 px-3 py-3 text-sm leading-6 text-rose-700">
                审计记录会匿名化保留，邮箱、IP、User-Agent 和资源标识会从个人相关历史事件中移除。
              </div>
              <Field label="输入当前邮箱确认">
                <input
                  className="input"
                  value={confirmEmail}
                  onChange={(event) => setConfirmEmail(event.target.value)}
                  placeholder={user?.email || 'email@example.com'}
                  autoComplete="off"
                />
              </Field>
              <Button type="button" variant="danger" className="w-full" disabled={!canDelete || deleting} onClick={handleDelete}>
                <Trash2 size={16} />
                {deleting ? '注销中...' : '注销账号'}
              </Button>
            </div>
          </Card>
        </div>
      </div>
    </AppShell>
  )
}
