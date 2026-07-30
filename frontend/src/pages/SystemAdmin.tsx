import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router'
import { ArrowLeft, BrainCircuit, CheckCircle2, CreditCard, Database, RefreshCw, ShieldCheck } from 'lucide-react'
import AppShell from '../components/AppShell'
import { Badge, Button, Card, EmptyState, Field, LoadingState, StatTile } from '../components/ui'
import { auditApi, AuditLog } from '../services/audit'
import { businessApi, AdminUsageSummary, BusinessEntitlements } from '../services/business'
import { systemApi, SystemStatus } from '../services/system'

function auditTone(eventType: string): 'neutral' | 'success' | 'warning' | 'danger' | 'info' {
  if (eventType.includes('delete')) return 'danger'
  if (eventType.includes('grant') || eventType.includes('export')) return 'warning'
  if (eventType.includes('login') || eventType.includes('register')) return 'success'
  if (eventType.includes('upload') || eventType.includes('finish')) return 'info'
  return 'neutral'
}

function formatMetadata(metadata: Record<string, unknown>) {
  const text = JSON.stringify(metadata || {})
  return text.length > 140 ? `${text.slice(0, 140)}...` : text
}

export default function SystemAdminPage() {
  const navigate = useNavigate()
  const [status, setStatus] = useState<SystemStatus | null>(null)
  const [business, setBusiness] = useState<BusinessEntitlements | null>(null)
  const [adminSummary, setAdminSummary] = useState<AdminUsageSummary | null>(null)
  const [auditLogs, setAuditLogs] = useState<AuditLog[]>([])
  const [auditEventType, setAuditEventType] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [adminError, setAdminError] = useState('')
  const [grantEmail, setGrantEmail] = useState('')
  const [grantPlan, setGrantPlan] = useState<'free' | 'pro' | 'enterprise'>('pro')
  const [grantDays, setGrantDays] = useState(30)
  const [grantNotes, setGrantNotes] = useState('')
  const [grantMessage, setGrantMessage] = useState('')
  const [granting, setGranting] = useState(false)
  const [backuping, setBackuping] = useState(false)
  const [reindexing, setReindexing] = useState(false)
  const [reindexMessage, setReindexMessage] = useState('')

  useEffect(() => {
    loadData()
  }, [])

  const loadData = async () => {
    setLoading(true)
    setError('')
    setAdminError('')
    try {
      const [statusRes, businessRes] = await Promise.all([systemApi.status(), businessApi.entitlements()])
        setStatus(statusRes.data)
        setBusiness(businessRes.data)
      try {
        const [adminRes, auditRes] = await Promise.all([
          businessApi.adminUsageSummary(),
          auditApi.adminLogs({ limit: 80, event_type: auditEventType.trim() || undefined }),
        ])
        setAdminSummary(adminRes.data)
        setAuditLogs(auditRes.data.logs)
      } catch (err: any) {
        setAdminSummary(null)
        setAuditLogs([])
        setAdminError(err.response?.data?.detail || '当前账号没有管理员权限')
      }
    } catch (err: any) {
      setError(err.response?.data?.detail || '系统巡检加载失败')
    } finally {
      setLoading(false)
    }
  }

  const handleGrantPlan = async (event: React.FormEvent) => {
    event.preventDefault()
    setGrantMessage('')
    setAdminError('')
    setGranting(true)
    try {
      const res = await businessApi.grantPlan({
        email: grantEmail.trim(),
        plan: grantPlan,
        days: grantPlan === 'enterprise' ? undefined : grantDays,
        notes: grantNotes.trim() || undefined,
      })
      setGrantMessage(`${res.data.message}：${res.data.plan}`)
      setGrantEmail('')
      setGrantNotes('')
      const [adminRes, auditRes] = await Promise.all([
        businessApi.adminUsageSummary(),
        auditApi.adminLogs({ limit: 80, event_type: auditEventType.trim() || undefined }),
      ])
      setAdminSummary(adminRes.data)
      setAuditLogs(auditRes.data.logs)
    } catch (err: any) {
      setAdminError(err.response?.data?.detail || '人工开通失败')
    } finally {
      setGranting(false)
    }
  }

  const handleLoadAuditLogs = async () => {
    setAdminError('')
    try {
      const res = await auditApi.adminLogs({ limit: 120, event_type: auditEventType.trim() || undefined })
      setAuditLogs(res.data.logs)
    } catch (err: any) {
      setAuditLogs([])
      setAdminError(err.response?.data?.detail || '审计日志加载失败')
    }
  }

  const handleBackup = async () => {
    setAdminError('')
    setBackuping(true)
    try {
      await systemApi.adminBackup()
      const statusRes = await systemApi.status()
      setStatus(statusRes.data)
    } catch (err: any) {
      setAdminError(err.response?.data?.detail || '备份创建失败')
    } finally {
      setBackuping(false)
    }
  }

  const handleReindexResumes = async () => {
    setAdminError('')
    setReindexMessage('')
    setReindexing(true)
    try {
      const res = await systemApi.adminReindexResumes({ only_missing: true })
      const statusRes = await systemApi.status()
      setStatus(statusRes.data)
      setReindexMessage(
        `已处理 ${res.data.processed_count} 份简历，写入 ${res.data.indexed_count} 个向量点，跳过 ${res.data.skipped_count} 份。`,
      )
    } catch (err: any) {
      setAdminError(err.response?.data?.detail || '简历向量索引回填失败')
    } finally {
      setReindexing(false)
    }
  }

  if (loading) return <LoadingState label="正在加载系统巡检" />

  return (
    <AppShell
      title="系统巡检"
      description="面向部署、运营和发布前检查；普通求职工作流不展示这些内部信息。"
      actions={
        <Button type="button" variant="secondary" onClick={() => navigate('/resumes')}>
          <ArrowLeft size={16} />
          返回工作台
        </Button>
      }
    >
      <div className="space-y-6">
        {error && <div className="rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div>}

        {status ? (
          <>
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
              <StatTile label="数据库" value={status.database.driver} meta={status.database.ok ? '连接正常' : status.database.error} icon={<Database size={18} />} />
              <StatTile label="模型" value={status.llm.provider} meta={status.llm.local_fallback ? '本地兜底/未配置真实 Key' : status.llm.model} icon={<BrainCircuit size={18} />} />
              <StatTile label="RAG 知识" value={status.rag.chunk_count} meta={`${status.rag.document_count} 个知识文档`} icon={<ShieldCheck size={18} />} />
              <StatTile
                label="发布检查"
                value={status.release.publishable ? '通过' : `${status.release.critical_count} 阻断`}
                meta={`${status.release.critical_count} critical / ${status.release.warning_count} warning`}
                icon={<CheckCircle2 size={18} />}
              />
            </div>

            {adminSummary && (
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
                <StatTile label="注册用户" value={adminSummary.totals.users} meta={`${adminSummary.totals.billing_accounts} 个权益账号`} icon={<CreditCard size={18} />} />
                <StatTile label="简历/面试" value={`${adminSummary.totals.resumes}/${adminSummary.totals.interviews}`} meta={`${adminSummary.window_days} 天窗口`} icon={<Database size={18} />} />
                <StatTile label="LLM 调用" value={adminSummary.totals.llm_call_count} meta={`${adminSummary.totals.estimated_input_tokens + adminSummary.totals.estimated_output_tokens} 估算 tokens`} icon={<BrainCircuit size={18} />} />
                <StatTile label="估算成本" value={`¥${adminSummary.totals.estimated_cost_cny}`} meta={`${adminSummary.totals.usage_records} 条用量记录`} icon={<ShieldCheck size={18} />} />
              </div>
            )}

            <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
              <Card>
                <div className="mb-5">
                  <h2 className="card-title">发布整改项</h2>
                  <p className="card-subtitle">生产发布前 critical 必须清零，warning 需要明确 owner 和处理计划。</p>
                </div>
                <div className="space-y-3">
                  {status.release.checks.map((check) => (
                    <div key={check.key} className="rounded-lg border border-slate-200 bg-white p-4">
                      <div className="mb-2 flex flex-wrap items-center gap-2">
                        <Badge tone={check.severity === 'pass' ? 'success' : check.severity === 'warning' ? 'warning' : 'danger'}>
                          {check.severity}
                        </Badge>
                        <span className="font-semibold text-slate-950">{check.key}</span>
                      </div>
                      <p className="text-sm leading-6 text-slate-700">{check.message}</p>
                      <p className="mt-2 text-sm leading-6 text-slate-500">{check.recommendation}</p>
                    </div>
                  ))}
                </div>
              </Card>

              <div className="space-y-6">
                <Card>
                  <div className="mb-5 flex items-start justify-between gap-4">
                    <div>
                      <h2 className="card-title">运行配置</h2>
                      <p className="card-subtitle">仅展示不含密钥的运行摘要。</p>
                    </div>
                    <Badge tone={status.environment === 'production' ? 'success' : 'warning'}>{status.environment}</Badge>
                  </div>
                  <div className="space-y-3 text-sm">
                    <div className="flex items-center justify-between rounded-md bg-slate-50 px-3 py-2">
                      <span className="text-slate-500">公开地址</span>
                      <span className="truncate pl-3 font-semibold text-slate-900">{status.public_base_url}</span>
                    </div>
                    <div className="flex items-center justify-between rounded-md bg-slate-50 px-3 py-2">
                      <span className="text-slate-500">API 限流</span>
                      <span className="font-semibold text-slate-900">
                        {status.security.api_requests_per_window}/{status.security.rate_limit_window_seconds}s
                      </span>
                    </div>
                    <div className="flex items-center justify-between rounded-md bg-slate-50 px-3 py-2">
                      <span className="text-slate-500">文件上限</span>
                      <span className="font-semibold text-slate-900">{status.limits.max_file_size_mb} MB</span>
                    </div>
                    <div className="flex items-center justify-between rounded-md bg-slate-50 px-3 py-2">
                      <span className="text-slate-500">管理员</span>
                      <span className="font-semibold text-slate-900">{status.security.admin_enabled ? '已配置' : '未配置'}</span>
                    </div>
                  </div>
                </Card>

                <Card>
                  <div className="mb-5 flex items-start justify-between gap-4">
                    <div>
                      <h2 className="card-title">队列与检索</h2>
                      <p className="card-subtitle">异步任务、Qdrant 和 rerank 的运行摘要。</p>
                    </div>
                    <Badge tone={status.operations.task_queue?.runtime.available ? 'success' : 'danger'}>
                      {status.operations.task_queue?.runtime.backend || 'local'}
                    </Badge>
                  </div>
                  <div className="space-y-3 text-sm">
                    {reindexMessage && (
                      <div className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-emerald-700">
                        {reindexMessage}
                      </div>
                    )}
                    <div className="grid grid-cols-2 gap-3">
                      <div className="rounded-md bg-slate-50 px-3 py-3">
                        <div className="text-xs text-slate-500">排队任务</div>
                        <div className="mt-1 font-bold text-slate-950">{status.operations.task_queue?.status_counts.queued || 0}</div>
                      </div>
                      <div className="rounded-md bg-slate-50 px-3 py-3">
                        <div className="text-xs text-slate-500">失败任务</div>
                        <div className="mt-1 font-bold text-slate-950">{status.operations.task_queue?.status_counts.failed || 0}</div>
                      </div>
                      <div className="rounded-md bg-slate-50 px-3 py-3">
                        <div className="text-xs text-slate-500">平均排队</div>
                        <div className="mt-1 font-bold text-slate-950">{status.operations.task_queue?.avg_queue_wait_ms || 0}ms</div>
                      </div>
                      <div className="rounded-md bg-slate-50 px-3 py-3">
                        <div className="text-xs text-slate-500">平均执行</div>
                        <div className="mt-1 font-bold text-slate-950">{status.operations.task_queue?.avg_execution_ms || 0}ms</div>
                      </div>
                      <div className="rounded-md bg-slate-50 px-3 py-3">
                        <div className="text-xs text-slate-500">SQL 简历切片</div>
                        <div className="mt-1 font-bold text-slate-950">{status.rag.resume_chunk_count || 0}</div>
                      </div>
                      <div className="rounded-md bg-slate-50 px-3 py-3">
                        <div className="text-xs text-slate-500">Qdrant 简历点</div>
                        <div className="mt-1 font-bold text-slate-950">{status.rag.vector_store?.resume_points_count || 0}</div>
                      </div>
                    </div>
                    <div className="rounded-md bg-slate-50 px-3 py-2">
                      <div className="text-xs text-slate-500">Rerank</div>
                      <div className="mt-1 font-semibold text-slate-900">
                        {status.rag.rerank?.enabled ? `${status.rag.rerank.provider} · ${status.rag.rerank.model}` : '未启用'}
                      </div>
                    </div>
                    <div className="rounded-md bg-slate-50 px-3 py-2">
                      <div className="text-xs text-slate-500">简历向量点</div>
                      <div className="mt-1 font-semibold text-slate-900">
                        {status.rag.vector_store?.resume_points_count || 0} / {status.rag.vector_store?.resume_actual_vector_size || '-'} 维
                      </div>
                    </div>
                    {adminSummary && (
                      <Button type="button" variant="secondary" className="w-full" onClick={handleReindexResumes} disabled={reindexing}>
                        <RefreshCw size={16} />
                        {reindexing ? '回填中...' : '回填简历向量索引'}
                      </Button>
                    )}
                  </div>
                </Card>

                <Card>
                  <div className="mb-5 flex items-start justify-between gap-4">
                    <div>
                      <h2 className="card-title">运维能力</h2>
                      <p className="card-subtitle">监控、备份和灰度配置。</p>
                    </div>
                    <Badge tone={status.operations.backup.enabled ? 'success' : 'warning'}>{status.operations.release.deployment_color}</Badge>
                  </div>
                  <div className="space-y-3 text-sm">
                    <div className="grid grid-cols-2 gap-3">
                      <div className="rounded-md bg-slate-50 px-3 py-3">
                        <div className="text-xs text-slate-500">请求数</div>
                        <div className="mt-1 font-bold text-slate-950">{status.operations.metrics.total_requests}</div>
                      </div>
                      <div className="rounded-md bg-slate-50 px-3 py-3">
                        <div className="text-xs text-slate-500">P95</div>
                        <div className="mt-1 font-bold text-slate-950">{status.operations.metrics.p95_duration_ms}ms</div>
                      </div>
                      <div className="rounded-md bg-slate-50 px-3 py-3">
                        <div className="text-xs text-slate-500">备份数</div>
                        <div className="mt-1 font-bold text-slate-950">{status.operations.backup.backup_count}</div>
                      </div>
                      <div className="rounded-md bg-slate-50 px-3 py-3">
                        <div className="text-xs text-slate-500">灰度</div>
                        <div className="mt-1 font-bold text-slate-950">{status.operations.release.canary_percent}%</div>
                      </div>
                    </div>
                    <div className="rounded-md bg-slate-50 px-3 py-2">
                      <div className="text-xs text-slate-500">最新备份</div>
                      <div className="mt-1 truncate font-semibold text-slate-900">
                        {status.operations.backup.latest_backup?.filename || '暂无'}
                      </div>
                    </div>
                    {adminSummary && (
                      <Button type="button" variant="secondary" className="w-full" onClick={handleBackup} disabled={backuping || !status.operations.backup.database_supported}>
                        <Database size={16} />
                        {backuping ? '备份中...' : '创建备份'}
                      </Button>
                    )}
                  </div>
                </Card>

                <Card>
                  <div className="mb-5 flex items-start justify-between gap-4">
                    <div>
                      <h2 className="card-title">商业配置</h2>
                      <p className="card-subtitle">收费入口、额度和升级方式。</p>
                    </div>
                    <CreditCard size={18} className="text-cyan-700" />
                  </div>
                  {business ? (
                    <div className="space-y-3 text-sm">
                      <div className="flex items-center justify-between rounded-md bg-slate-50 px-3 py-2">
                        <span className="text-slate-500">当前套餐</span>
                        <span className="font-semibold text-slate-900">{business.plan.name}</span>
                      </div>
                      <div className="flex items-center justify-between rounded-md bg-slate-50 px-3 py-2">
                        <span className="text-slate-500">计费开关</span>
                        <span className="font-semibold text-slate-900">{business.plan.billing_enabled ? '开启' : '关闭'}</span>
                      </div>
                      <div className="flex items-center justify-between rounded-md bg-slate-50 px-3 py-2">
                        <span className="text-slate-500">支付渠道</span>
                        <span className="font-semibold text-slate-900">{business.plan.payment_provider}</span>
                      </div>
                      <div className="flex items-center justify-between rounded-md bg-slate-50 px-3 py-2">
                        <span className="text-slate-500">Pro 价格</span>
                        <span className="font-semibold text-slate-900">¥{business.upgrade.price_cny}/月</span>
                      </div>
                    </div>
                  ) : (
                    <EmptyState title="商业配置不可用" />
                  )}
                </Card>

                <Card>
                  <div className="mb-5 flex items-start justify-between gap-4">
                    <div>
                      <h2 className="card-title">人工开通</h2>
                      <p className="card-subtitle">适合 manual 收款、机构试点和客服补偿。</p>
                    </div>
                    <Badge tone={adminSummary ? 'success' : 'warning'}>{adminSummary ? '管理员' : '无权限'}</Badge>
                  </div>
                  {adminSummary ? (
                    <form onSubmit={handleGrantPlan} className="space-y-4">
                      {grantMessage && <div className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">{grantMessage}</div>}
                      {adminError && <div className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">{adminError}</div>}
                      <Field label="用户邮箱">
                        <input className="input" type="email" value={grantEmail} onChange={(event) => setGrantEmail(event.target.value)} required />
                      </Field>
                      <div className="grid grid-cols-2 gap-3">
                        <Field label="套餐">
                          <select className="select" value={grantPlan} onChange={(event) => setGrantPlan(event.target.value as 'free' | 'pro' | 'enterprise')}>
                            <option value="free">免费版</option>
                            <option value="pro">Pro 月卡</option>
                            <option value="enterprise">机构版</option>
                          </select>
                        </Field>
                        <Field label="天数">
                          <input
                            className="input"
                            type="number"
                            min={1}
                            max={3650}
                            value={grantDays}
                            onChange={(event) => setGrantDays(Number(event.target.value))}
                            disabled={grantPlan === 'enterprise'}
                          />
                        </Field>
                      </div>
                      <Field label="备注">
                        <textarea className="textarea min-h-24" value={grantNotes} onChange={(event) => setGrantNotes(event.target.value)} maxLength={500} />
                      </Field>
                      <Button type="submit" className="w-full" disabled={granting || !grantEmail.trim()}>
                        <CreditCard size={16} />
                        {granting ? '开通中...' : '开通套餐'}
                      </Button>
                    </form>
                  ) : (
                    <EmptyState title="当前账号不是管理员" description={adminError || '配置 ADMIN_EMAILS 后可使用人工开通和运营摘要。'} />
                  )}
                </Card>

                {adminSummary && (
                  <Card>
                    <div className="mb-5">
                      <h2 className="card-title">升级意向</h2>
                      <p className="card-subtitle">最近提交升级申请的用户。</p>
                    </div>
                    <div className="space-y-3">
                      {adminSummary.upgrade_requests.map((item) => (
                        <div key={item.id} className="rounded-md bg-slate-50 px-3 py-3 text-sm">
                          <div className="font-semibold text-slate-950">{item.email}</div>
                          <div className="mt-1 text-xs text-slate-500">{new Date(item.created_at).toLocaleString()}</div>
                        </div>
                      ))}
                      {adminSummary.upgrade_requests.length === 0 && <EmptyState title="暂无升级意向" />}
                    </div>
                  </Card>
                )}
              </div>
            </div>

            {adminSummary && (
              <Card>
                <div className="mb-5 flex flex-col justify-between gap-4 lg:flex-row lg:items-start">
                  <div>
                    <h2 className="card-title">审计日志</h2>
                    <p className="card-subtitle">账号、简历、面试、计费和导出等关键事件。</p>
                  </div>
                  <div className="flex w-full flex-col gap-2 sm:flex-row lg:w-auto">
                    <input
                      className="input sm:w-64"
                      value={auditEventType}
                      onChange={(event) => setAuditEventType(event.target.value)}
                      placeholder="event_type"
                    />
                    <Button type="button" variant="secondary" onClick={handleLoadAuditLogs}>
                      <RefreshCw size={16} />
                      刷新
                    </Button>
                  </div>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[860px] text-left text-sm">
                    <thead>
                      <tr className="border-b border-slate-200 text-xs font-semibold uppercase tracking-normal text-slate-500">
                        <th className="px-3 py-3">事件</th>
                        <th className="px-3 py-3">操作者</th>
                        <th className="px-3 py-3">资源</th>
                        <th className="px-3 py-3">时间</th>
                        <th className="px-3 py-3">元数据</th>
                      </tr>
                    </thead>
                    <tbody>
                      {auditLogs.map((record) => (
                        <tr key={record.id} className="border-b border-slate-100 align-top">
                          <td className="px-3 py-3">
                            <Badge tone={auditTone(record.event_type)}>{record.event_type}</Badge>
                          </td>
                          <td className="px-3 py-3">
                            <div className="font-semibold text-slate-900">{record.actor_email || '匿名/系统'}</div>
                            <div className="mt-1 text-xs text-slate-500">{record.ip_address || '-'}</div>
                          </td>
                          <td className="px-3 py-3">
                            <div className="font-semibold text-slate-900">{record.resource_type}</div>
                            <div className="mt-1 max-w-56 truncate text-xs text-slate-500">{record.resource_id || '-'}</div>
                          </td>
                          <td className="px-3 py-3 text-slate-600">{new Date(record.created_at).toLocaleString()}</td>
                          <td className="px-3 py-3">
                            <code className="block max-w-80 whitespace-normal break-words rounded-md bg-slate-50 px-2 py-1 text-xs text-slate-600">
                              {formatMetadata(record.metadata)}
                            </code>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {auditLogs.length === 0 && <EmptyState title="暂无审计日志" />}
                </div>
              </Card>
            )}
          </>
        ) : (
          <EmptyState title="系统状态不可用" description="请确认后端服务可访问且当前账号已登录。" />
        )}
      </div>
    </AppShell>
  )
}
