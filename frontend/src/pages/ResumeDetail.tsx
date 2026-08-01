import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { useParams, useNavigate } from 'react-router'
import {
  ArrowLeft,
  BriefcaseBusiness,
  Download,
  FileJson,
  FileCheck2,
  FilePenLine,
  FileText,
  Gauge,
  History,
  ListChecks,
  Play,
  RefreshCcw,
  Save,
  SearchCheck,
  ShieldCheck,
  Target,
  Trash2,
  Wand2,
  X,
} from 'lucide-react'
import AppShell from '../components/AppShell'
import { Badge, Button, Card, EmptyState, Field, LoadingState, ProgressBar, StatTile } from '../components/ui'
import { resumeApi, type AtsReport, type Resume, type ResumeChunk, type ResumeVersion } from '../services/resume'
import { taskApi, type AsyncTask } from '../services/tasks'
import { templateApi, ResumeTemplate } from '../services/template'
import { businessApi, BusinessEntitlements } from '../services/business'
import {
  ResumeStructuredEditor,
  ResumeStructuredPreview,
  normalizeResumeData,
  type ResumeData,
} from '../components/ResumeStructuredEditor'

function countItems(value: unknown): number {
  return Array.isArray(value) ? value.length : 0
}

function referencesFrom(data: any): Array<{ title?: string; category?: string; score?: number }> {
  return Array.isArray(data?.rag_references) ? data.rag_references : []
}

function atsFrom(data: any): AtsReport | null {
  return data?.ats_report && Array.isArray(data.ats_report.dimensions) ? data.ats_report : null
}

function changeDetailsFrom(data: any): Array<{ section?: string; before?: string; after?: string; reason?: string; evidence?: string }> {
  return Array.isArray(data?.change_details) ? data.change_details.filter((item: any) => item && typeof item === 'object') : []
}

const changeSectionLabels: Record<string, string> = {
  personal: '基本信息',
  education: '教育背景',
  experience: '实习/工作经历',
  projects: '项目经历',
  project: '项目经历',
  skills: '技能关键词',
  summary: '自我评价',
}

function changeSectionLabel(section?: string) {
  if (!section) return '简历内容'
  return changeSectionLabels[section] || section
}

function commonPrefixLength(left: string, right: string) {
  const limit = Math.min(left.length, right.length)
  let index = 0
  while (index < limit && left[index] === right[index]) index += 1
  return index
}

function commonSuffixLength(left: string, right: string, prefixLength: number) {
  const limit = Math.min(left.length, right.length) - prefixLength
  let index = 0
  while (
    index < limit &&
    left[left.length - 1 - index] === right[right.length - 1 - index]
  ) {
    index += 1
  }
  return index
}

function highlightChangedText(before?: string, after?: string): ReactNode {
  const previous = before || ''
  const current = after || ''
  if (!current) return '-'
  if (!previous || previous === current) return current

  const prefixLength = commonPrefixLength(previous, current)
  const suffixLength = commonSuffixLength(previous, current, prefixLength)
  const changedEnd = current.length - suffixLength
  const prefix = current.slice(0, prefixLength)
  const changed = current.slice(prefixLength, changedEnd)
  const suffix = current.slice(changedEnd)

  if (!changed) return current
  return (
    <>
      {prefix}
      <mark className="rounded-sm bg-amber-100 px-0.5 text-amber-950 ring-1 ring-amber-200">
        {changed}
      </mark>
      {suffix}
    </>
  )
}

function scoreTone(score: number): 'success' | 'warning' | 'danger' {
  if (score >= 80) return 'success'
  if (score >= 65) return 'warning'
  return 'danger'
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

function AtsReportPanel({ report }: { report: AtsReport }) {
  const evidence = report.requirement_evidence || []
  return (
    <section className="rounded-lg border border-slate-200 bg-slate-50 p-4">
      <div className="mb-4 flex flex-col justify-between gap-3 lg:flex-row lg:items-center">
        <div>
          <h3 className="font-semibold text-slate-950">JD 匹配评分</h3>
          <p className="mt-1 text-sm leading-6 text-slate-500">基于简历片段检索、RRF 融合和规则评分生成。</p>
        </div>
        <div className="flex items-center gap-2">
          <Gauge size={18} className="text-slate-600" />
          <span className="text-2xl font-bold text-slate-950">{report.total_score}</span>
          <span className="text-sm text-slate-500">/ 100</span>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {(report.dimensions || []).map((dimension) => (
          <div key={dimension.key} className="rounded-md border border-slate-200 bg-white p-3">
            <div className="mb-2 flex items-center justify-between gap-2">
              <span className="text-sm font-semibold text-slate-900">{dimension.name}</span>
              <Badge tone={scoreTone(dimension.score)}>{dimension.score}</Badge>
            </div>
            <ProgressBar value={dimension.score} />
            {dimension.covered?.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-1.5">
                {dimension.covered.slice(0, 5).map((item) => <Badge key={item} tone="success">{item}</Badge>)}
              </div>
            )}
            {dimension.missing?.length > 0 && (
              <div className="mt-3 text-xs leading-5 text-rose-700">缺口：{dimension.missing.slice(0, 4).join('、')}</div>
            )}
            {dimension.risk?.length > 0 && (
              <div className="mt-2 text-xs leading-5 text-amber-700">风险：{dimension.risk.slice(0, 3).join('；')}</div>
            )}
            <div className="mt-2 text-xs leading-5 text-slate-500">{dimension.suggestion}</div>
          </div>
        ))}
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <div className="rounded-md border border-slate-200 bg-white p-3">
          <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-slate-900">
            <ShieldCheck size={16} className="text-emerald-700" />
            投递建议
          </div>
          <ul className="space-y-1 text-sm leading-6 text-slate-600">
            {(report.delivery_advice || []).map((item) => <li key={item}>- {item}</li>)}
          </ul>
        </div>
        <div className="rounded-md border border-slate-200 bg-white p-3">
          <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-slate-900">
            <Target size={16} className="text-slate-600" />
            命中证据
          </div>
          <div className="space-y-2">
            {evidence.slice(0, 4).map((item, index) => (
              <div key={`${item.requirement}-${index}`} className="rounded-md bg-slate-50 p-2 text-xs leading-5 text-slate-600">
                <div className="font-semibold text-slate-900">{item.requirement} · {item.section_label || item.section}</div>
                <div>{item.item_title}</div>
                <div className="mt-1">{item.excerpt}</div>
              </div>
            ))}
            {evidence.length === 0 && <div className="text-sm text-slate-500">暂无明确证据，建议先补齐项目或实习细节。</div>}
          </div>
        </div>
      </div>
    </section>
  )
}

function ChangeDetailsPanel({ changes }: { changes: ReturnType<typeof changeDetailsFrom> }) {
  if (!changes.length) return null
  return (
    <section className="rounded-lg border border-slate-200 bg-white" data-testid="change-details-panel">
      <div className="border-b border-slate-200 px-4 py-3">
        <h3 className="font-semibold text-slate-950">修改前后对比</h3>
        <p className="mt-1 text-sm text-slate-500">只展示基于原有素材的调整、增补和改写原因。</p>
      </div>
      <div className="divide-y divide-slate-200">
        {changes.slice(0, 20).map((item, index) => (
          <div key={`${item.section}-${index}`} className="grid gap-3 p-4 lg:grid-cols-[0.7fr_1fr_1fr_1fr]">
            <div>
              <div className="text-xs text-slate-500">模块</div>
              <div className="mt-1 font-semibold text-slate-900">{changeSectionLabel(item.section)}</div>
            </div>
            <div>
              <div className="text-xs text-slate-500">修改前</div>
              <div className="mt-1 text-sm leading-6 text-slate-600">{item.before || '原简历未单独成句'}</div>
            </div>
            <div>
              <div className="text-xs text-slate-500">修改后</div>
              <div className="mt-1 text-sm leading-6 text-slate-900">{highlightChangedText(item.before, item.after)}</div>
            </div>
            <div>
              <div className="text-xs text-slate-500">改动说明</div>
              <div className="mt-1 text-sm leading-6 text-slate-600">{item.reason || item.evidence || '-'}</div>
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}

export default function ResumeDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [resume, setResume] = useState<Resume | null>(null)
  const [chunks, setChunks] = useState<ResumeChunk[]>([])
  const [versions, setVersions] = useState<ResumeVersion[]>([])
  const [activeTask, setActiveTask] = useState<AsyncTask | null>(null)
  const [templates, setTemplates] = useState<ResumeTemplate[]>([])
  const [business, setBusiness] = useState<BusinessEntitlements | null>(null)
  const [selectedTemplate, setSelectedTemplate] = useState('')
  const [jdText, setJdText] = useState('')
  const [loading, setLoading] = useState(false)
  const [reindexing, setReindexing] = useState(false)
  const [activeTab, setActiveTab] = useState<'parsed' | 'optimized'>('parsed')
  const [editing, setEditing] = useState(false)
  const [editorData, setEditorData] = useState<ResumeData>({})
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    if (!id) return
    loadData()
  }, [id])

  useEffect(() => {
    if (!resume) return
    const currentData = activeTab === 'optimized' ? resume.optimized_data : resume.parsed_data
    setEditorData(normalizeResumeData(currentData || {}))
    setEditing(false)
    setError('')
  }, [resume, activeTab])

  const displayData = activeTab === 'optimized' ? resume?.optimized_data : resume?.parsed_data
  const references = referencesFrom(resume?.optimized_data)
  const atsReport = atsFrom(resume?.optimized_data)
  const changeDetails = changeDetailsFrom(resume?.optimized_data)
  const optimizePaywallBlocked = Boolean(
    business?.entitlements.paywall_active && !business.entitlements.can_optimize_resume,
  )
  const jdAdaptPaywallBlocked = Boolean(
    business?.entitlements.paywall_active && !business.entitlements.can_adapt_jd,
  )

  const stats = useMemo(() => {
    const data = resume?.optimized_data || resume?.parsed_data || {}
    return {
      projects: countItems(data.projects),
      experience: countItems(data.experience),
      skills: countItems(data.skills),
      points:
        [...(data.projects || []), ...(data.experience || [])].reduce(
          (sum: number, item: any) => sum + countItems(item.interview_points),
          0,
        ) || 0,
      chunks: chunks.length,
    }
  }, [resume, chunks.length])

  const loadData = async () => {
    setError('')
    try {
      const [resumeRes, templateRes, businessRes, chunkRes, versionRes] = await Promise.all([
        resumeApi.get(id!),
        templateApi.list(),
        businessApi.entitlements(),
        resumeApi.chunks(id!),
        resumeApi.versions(id!),
      ])
      setResume(resumeRes.data)
      setTemplates(templateRes.data)
      setBusiness(businessRes.data)
      setChunks(chunkRes.data)
      setVersions(versionRes.data)
      setSelectedTemplate(resumeRes.data.template_id || '')
    } catch (err: any) {
      setError(err.response?.data?.detail || '简历加载失败')
    }
  }

  const handleOptimize = async () => {
    if (!selectedTemplate) return
    setLoading(true)
    setError('')
    setMessage('')
    try {
      const res = await resumeApi.optimize(id!, selectedTemplate)
      setResume(res.data)
      setActiveTab('optimized')
      setMessage('模板优化完成，已写入 RAG 来源。')
      businessApi.entitlements().then((businessRes) => setBusiness(businessRes.data)).catch(() => undefined)
    } catch (err: any) {
      setError(err.response?.data?.detail || '优化失败')
    } finally {
      setLoading(false)
    }
  }

  const handleAdaptJD = async () => {
    if (!jdText.trim()) return
    setLoading(true)
    setError('')
    setMessage('')
    try {
      const taskRes = await resumeApi.adaptJDTask(id!, jdText.trim())
      let task: AsyncTask = taskRes.data.task
      setActiveTask(task)
      while (!['success', 'failed', 'cancelled'].includes(task.status)) {
        await new Promise((resolve) => window.setTimeout(resolve, 1500))
        const next = await taskApi.get(task.id)
        task = next.data
        setActiveTask(task)
      }
      if (task.status !== 'success') {
        throw new Error(task.error_message || 'JD 优化任务失败')
      }
      const [res, chunkRes, versionRes] = await Promise.all([
        resumeApi.get(id!),
        resumeApi.chunks(id!),
        resumeApi.versions(id!),
      ])
      setResume(res.data)
      setChunks(chunkRes.data)
      setVersions(versionRes.data)
      setActiveTab('optimized')
      setMessage('JD 定向完善完成，匹配度和优化结果已更新。')
      businessApi.entitlements().then((businessRes) => setBusiness(businessRes.data)).catch(() => undefined)
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'JD 适配失败')
    } finally {
      setLoading(false)
      setActiveTask(null)
    }
  }

  const handleUpdate = async (data: Partial<Resume>) => {
    try {
      const res = await resumeApi.update(id!, data)
      const [chunkRes, versionRes] = await Promise.all([resumeApi.chunks(id!), resumeApi.versions(id!)])
      setResume(res.data)
      setChunks(chunkRes.data)
      setVersions(versionRes.data)
      setEditing(false)
      setError('')
      setMessage('结构化内容已保存。')
    } catch (err: any) {
      setError(err.response?.data?.detail || '保存失败，请检查网络或稍后重试')
    }
  }

  const handleSaveStructured = async () => {
    await handleUpdate(activeTab === 'optimized' ? { optimized_data: editorData } : { parsed_data: editorData })
  }

  const handleReindex = async () => {
    setReindexing(true)
    setError('')
    setMessage('')
    try {
      await resumeApi.reindex(id!)
      const chunkRes = await resumeApi.chunks(id!)
      setChunks(chunkRes.data)
      setMessage('简历证据索引已重建。')
    } catch (err: any) {
      setError(err.response?.data?.detail || '重建索引失败')
    } finally {
      setReindexing(false)
    }
  }

  const handleCreateDelivery = async () => {
    setError('')
    setMessage('')
    try {
      await resumeApi.createDeliveryVersion(id!)
      const versionRes = await resumeApi.versions(id!)
      setVersions(versionRes.data)
      setMessage('投递版已保存。')
    } catch (err: any) {
      setError(err.response?.data?.detail || '创建投递版失败')
    }
  }

  const handleRollback = async (versionId: string) => {
    setError('')
    setMessage('')
    try {
      const res = await resumeApi.rollbackVersion(id!, versionId)
      const [chunkRes, versionRes] = await Promise.all([resumeApi.chunks(id!), resumeApi.versions(id!)])
      setResume(res.data)
      setChunks(chunkRes.data)
      setVersions(versionRes.data)
      setActiveTab('optimized')
      setMessage('已回滚到选中版本。')
    } catch (err: any) {
      setError(err.response?.data?.detail || '回滚失败')
    }
  }

  const handleExportResume = async (variant: string, versionId?: string) => {
    setError('')
    try {
      const res = await resumeApi.exportDocx(id!, { variant, version_id: versionId })
      downloadBlob(res.data, `${resume?.title || '简历'}-${variant}.docx`)
      setMessage('Word 文件已生成。')
    } catch (err: any) {
      setError(err.response?.data?.detail || '导出失败')
    }
  }

  const handleDelete = async () => {
    if (!resume) return
    const confirmed = window.confirm(`确认删除「${resume.title}」？删除后无法恢复。`)
    if (!confirmed) return
    setLoading(true)
    try {
      await resumeApi.delete(resume.id)
      navigate('/resumes')
    } catch (err: any) {
      setError(err.response?.data?.detail || '删除失败')
    } finally {
      setLoading(false)
    }
  }

  if (!resume && !error) return <LoadingState label="正在加载简历详情" />

  if (!resume) {
    return (
      <AppShell title="简历详情" actions={<Button type="button" variant="secondary" onClick={() => navigate('/resumes')}>返回</Button>}>
        <EmptyState title="简历不可用" description={error || '请返回工作台重新选择简历。'} />
      </AppShell>
    )
  }

  return (
    <AppShell
      title={resume.title}
      description="编辑结构化简历、执行模板优化和 JD 定向完善，再进入模拟面试。"
      actions={
        <>
          <Button type="button" variant="secondary" onClick={() => navigate('/resumes')}>
            <ArrowLeft size={16} />
            返回
          </Button>
          <Button type="button" variant="success" onClick={() => navigate(`/interviews/new?resumeId=${resume.id}`)}>
            <Play size={16} />
            开始面试
          </Button>
        </>
      }
    >
      <div className="space-y-6">
        {error && <div className="rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div>}
        {message && <div className="rounded-md border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{message}</div>}

        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-5">
          <StatTile label="项目经历" value={stats.projects} meta="结构化项目数量" icon={<BriefcaseBusiness size={18} />} />
          <StatTile label="工作/实习" value={stats.experience} meta="可复盘经历数量" icon={<FileText size={18} />} />
          <StatTile label="技能关键词" value={stats.skills} meta="用于 JD 匹配" icon={<FileCheck2 size={18} />} />
          <StatTile label="面试要点" value={stats.points} meta="用于准备问题" icon={<ListChecks size={18} />} />
          <StatTile label="证据片段" value={stats.chunks} meta="用于 JD 相似度检索" icon={<SearchCheck size={18} />} />
        </div>

        <div className="grid grid-cols-1 gap-6 xl:grid-cols-[360px_minmax(0,1fr)]">
          <div className="space-y-6">
            <Card>
              <div className="mb-5">
                <h2 className="card-title">简历优化</h2>
                <p className="card-subtitle">选择岗位模板，RAG 会补充岗位表达和评分标准。</p>
              </div>
              <div className="space-y-4">
                <Field label="模板">
                  <select
                    value={selectedTemplate}
                    onChange={(event) => setSelectedTemplate(event.target.value)}
                    className="select"
                  >
                    <option value="">选择模板</option>
                    {templates.map((template) => (
                      <option key={template.id} value={template.id}>
                        {template.name}
                      </option>
                    ))}
                  </select>
                </Field>
                {optimizePaywallBlocked && (
                  <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
                    免费模板优化额度已用完，请升级 Pro 或联系管理员开通权益。
                  </div>
                )}
                <Button type="button" className="w-full" onClick={handleOptimize} disabled={loading || !selectedTemplate || optimizePaywallBlocked}>
                  <Wand2 size={16} />
                  {loading ? '处理中...' : optimizePaywallBlocked ? '需升级后优化' : '基于模板优化'}
                </Button>
              </div>
            </Card>

            <Card>
              <div className="mb-5">
                <h2 className="card-title">JD 定向完善</h2>
                <p className="card-subtitle">只做表达重组和重点调整，不新增未提供经历。</p>
              </div>
              <div className="space-y-4">
                <Field label="岗位 JD" hint={`${jdText.length}/40000 字符`}>
                  <textarea
                    placeholder="粘贴岗位职责和任职要求"
                    value={jdText}
                    onChange={(event) => setJdText(event.target.value)}
                    className="textarea min-h-44"
                    maxLength={40000}
                  />
                </Field>
                {jdAdaptPaywallBlocked && (
                  <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
                    免费 JD 适配额度已用完，请升级 Pro 或联系管理员开通权益。
                  </div>
                )}
                <Button type="button" className="w-full" onClick={handleAdaptJD} disabled={loading || !jdText.trim() || jdAdaptPaywallBlocked} data-testid="resume-adapt-jd-button">
                  <FilePenLine size={16} />
                  {loading ? '任务执行中...' : jdAdaptPaywallBlocked ? '需升级后适配' : '根据 JD 完善'}
                </Button>
                {activeTask && (
                  <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-3" data-testid="resume-task-progress">
                    <div className="mb-2 flex items-center justify-between gap-3 text-sm">
                      <span className="font-semibold text-slate-900">{activeTask.stage}</span>
                      <span className="text-slate-600">{activeTask.progress}%</span>
                    </div>
                    <ProgressBar value={activeTask.progress} />
                  </div>
                )}
                {resume.match_score !== null && (
                  <div className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
                    当前匹配度：<span className="font-bold">{resume.match_score}</span>
                  </div>
                )}
              </div>
            </Card>

            <Card data-testid="resume-evidence-index-card">
              <div className="mb-4 flex items-center justify-between gap-3">
                <div>
                  <h2 className="card-title">简历证据索引</h2>
                  <p className="card-subtitle">按模块切片后用于 JD 相似度检索。</p>
                </div>
                <Badge tone={chunks.length > 0 ? 'success' : 'warning'}>{chunks.length} 片</Badge>
              </div>
              <div className="space-y-3">
                {chunks.slice(0, 4).map((chunk) => (
                  <div key={chunk.id} className="rounded-md bg-slate-50 px-3 py-2 text-sm">
                    <div className="flex items-center justify-between gap-2">
                      <div className="font-semibold text-slate-900">{chunk.item_title || chunk.section}</div>
                      <Badge tone={chunk.embedding_status === 'indexed' ? 'success' : chunk.embedding_status === 'failed' ? 'danger' : 'neutral'}>
                        {chunk.embedding_status}
                      </Badge>
                    </div>
                    <div className="mt-1 max-h-10 overflow-hidden text-xs leading-5 text-slate-500">{chunk.content}</div>
                  </div>
                ))}
                {chunks.length === 0 && <EmptyState title="暂无证据片段" description="可以点击重建索引，系统会按技能、实习和项目切片。" />}
                <Button type="button" variant="secondary" className="w-full" onClick={handleReindex} disabled={reindexing || loading} data-testid="reindex-resume-button">
                  <RefreshCcw size={16} />
                  {reindexing ? '重建中...' : '重建简历索引'}
                </Button>
              </div>
            </Card>

            <Card>
              <div className="mb-4 flex items-center justify-between gap-3">
                <div>
                  <h2 className="card-title">简历版本</h2>
                  <p className="card-subtitle">原始版、优化版和投递版可回滚。</p>
                </div>
                <Badge tone="info">{versions.length} 版</Badge>
              </div>
              <div className="space-y-3">
                <div className="grid grid-cols-2 gap-2">
                  <Button type="button" variant="secondary" onClick={() => handleExportResume('optimized')}>
                    <Download size={16} />
                    导出优化版
                  </Button>
                  <Button type="button" variant="secondary" onClick={handleCreateDelivery}>
                    <History size={16} />
                    保存投递版
                  </Button>
                </div>
                <Button type="button" variant="secondary" className="w-full" onClick={() => handleExportResume('delivery')} data-testid="export-resume-delivery-button">
                  <Download size={16} />
                  导出投递版 Word
                </Button>
                <div className="space-y-2">
                  {versions.slice(0, 5).map((version) => (
                    <div key={version.id} className="rounded-md bg-slate-50 p-3 text-sm">
                      <div className="flex items-center justify-between gap-2">
                        <div className="font-semibold text-slate-900">v{version.version_number} · {version.title}</div>
                        <Badge tone={version.version_type === 'delivery' ? 'success' : version.version_type === 'original' ? 'neutral' : 'info'}>
                          {version.version_type}
                        </Badge>
                        {version.is_current && <Badge tone="success">当前</Badge>}
                      </div>
                      <div className="mt-1 text-xs text-slate-500">
                        {new Date(version.created_at).toLocaleString()}
                        {version.created_by ? ` · ${version.created_by}` : ''}
                        {version.source_job_id ? ` · 来源岗位 ${version.source_job_id.slice(0, 8)}` : ''}
                      </div>
                      {version.change_details?.length ? (
                        <div className="mt-1 text-xs text-slate-500">改动 {version.change_details.length} 处</div>
                      ) : null}
                      <div className="mt-2 flex gap-2">
                        <Button type="button" variant="ghost" size="sm" onClick={() => handleRollback(version.id)}>
                          回滚
                        </Button>
                        <Button type="button" variant="ghost" size="sm" onClick={() => handleExportResume(version.version_type, version.id)}>
                          导出
                        </Button>
                      </div>
                    </div>
                  ))}
                  {versions.length === 0 && <EmptyState title="暂无版本" description="上传或执行 JD 优化后会自动生成版本。" />}
                </div>
              </div>
            </Card>

            <Card>
              <div className="mb-4 flex items-center justify-between">
                <h2 className="card-title">RAG 来源</h2>
                <Badge tone="info">{references.length} 条</Badge>
              </div>
              <div className="space-y-2">
                {references.map((reference, index) => (
                  <div key={`${reference.title}-${index}`} className="rounded-md bg-slate-50 px-3 py-2 text-sm">
                    <div className="font-semibold text-slate-900">{reference.title || '知识片段'}</div>
                    <div className="mt-1 text-xs text-slate-500">
                      {reference.category || 'knowledge'} · score {reference.score ?? '-'}
                    </div>
                  </div>
                ))}
                {references.length === 0 && <EmptyState title="暂无 RAG 来源" description="执行优化或 JD 适配后会显示命中知识。" />}
              </div>
            </Card>

            <Button type="button" variant="danger" className="w-full" onClick={handleDelete} disabled={loading}>
              <Trash2 size={16} />
              删除简历
            </Button>
          </div>

          <Card>
            <div className="mb-4 flex flex-col justify-between gap-3 border-b border-slate-200 pb-4 lg:flex-row lg:items-center">
              <div className="flex gap-2">
                <Button
                  type="button"
                  variant={activeTab === 'parsed' ? 'primary' : 'secondary'}
                  size="sm"
                  onClick={() => setActiveTab('parsed')}
                >
                  <FileJson size={14} />
                  解析结果
                </Button>
                <Button
                  type="button"
                  variant={activeTab === 'optimized' ? 'primary' : 'secondary'}
                  size="sm"
                  onClick={() => setActiveTab('optimized')}
                >
                  <FileText size={14} />
                  优化结果
                </Button>
              </div>
              <div className="flex gap-2">
                {editing ? (
                  <>
                    <Button type="button" size="sm" onClick={handleSaveStructured}>
                      <Save size={14} />
                      保存
                    </Button>
                    <Button
                      type="button"
                      variant="secondary"
                      size="sm"
                      onClick={() => {
                        setEditorData(normalizeResumeData(displayData || {}))
                        setEditing(false)
                        setError('')
                      }}
                    >
                      <X size={14} />
                      取消
                    </Button>
                  </>
                ) : (
                  <Button type="button" variant="secondary" size="sm" onClick={() => setEditing(true)}>
                    <FileText size={14} />
                    编辑内容
                  </Button>
                )}
              </div>
            </div>

            {editing ? (
              <ResumeStructuredEditor value={editorData} onChange={setEditorData} />
            ) : (
              <div className="space-y-4">
                {atsReport && <AtsReportPanel report={atsReport} />}
                {activeTab === 'optimized' && <ChangeDetailsPanel changes={changeDetails} />}
                <ResumeStructuredPreview value={normalizeResumeData(displayData || {})} />
              </div>
            )}
          </Card>
        </div>
      </div>
    </AppShell>
  )
}
