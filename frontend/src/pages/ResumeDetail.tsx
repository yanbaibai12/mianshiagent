import { useEffect, useMemo, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  ArrowLeft,
  BrainCircuit,
  BriefcaseBusiness,
  FileJson,
  FileText,
  Play,
  Save,
  Sparkles,
  Trash2,
  Wand2,
  X,
} from 'lucide-react'
import AppShell from '../components/AppShell'
import { Badge, Button, Card, EmptyState, Field, LoadingState, StatTile } from '../components/ui'
import { resumeApi, Resume } from '../services/resume'
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

export default function ResumeDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [resume, setResume] = useState<Resume | null>(null)
  const [templates, setTemplates] = useState<ResumeTemplate[]>([])
  const [business, setBusiness] = useState<BusinessEntitlements | null>(null)
  const [selectedTemplate, setSelectedTemplate] = useState('')
  const [jdText, setJdText] = useState('')
  const [loading, setLoading] = useState(false)
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
    }
  }, [resume])

  const loadData = async () => {
    setError('')
    try {
      const [resumeRes, templateRes, businessRes] = await Promise.all([
        resumeApi.get(id!),
        templateApi.list(),
        businessApi.entitlements(),
      ])
      setResume(resumeRes.data)
      setTemplates(templateRes.data)
      setBusiness(businessRes.data)
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
      await resumeApi.adaptJD(id!, jdText.trim())
      const res = await resumeApi.get(id!)
      setResume(res.data)
      setActiveTab('optimized')
      setMessage('JD 定向完善完成，匹配度和优化结果已更新。')
      businessApi.entitlements().then((businessRes) => setBusiness(businessRes.data)).catch(() => undefined)
    } catch (err: any) {
      setError(err.response?.data?.detail || 'JD 适配失败')
    } finally {
      setLoading(false)
    }
  }

  const handleUpdate = async (data: Partial<Resume>) => {
    try {
      const res = await resumeApi.update(id!, data)
      setResume(res.data)
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

        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
          <StatTile label="项目经历" value={stats.projects} meta="结构化项目数量" icon={<BriefcaseBusiness size={18} />} />
          <StatTile label="工作/实习" value={stats.experience} meta="可复盘经历数量" icon={<FileText size={18} />} />
          <StatTile label="技能关键词" value={stats.skills} meta="用于 JD 匹配" icon={<Sparkles size={18} />} />
          <StatTile label="面试要点" value={stats.points} meta="用于自动出题" icon={<BrainCircuit size={18} />} />
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
                <Button type="button" className="w-full" onClick={handleAdaptJD} disabled={loading || !jdText.trim() || jdAdaptPaywallBlocked}>
                  <Sparkles size={16} />
                  {loading ? '处理中...' : jdAdaptPaywallBlocked ? '需升级后适配' : '根据 JD 完善'}
                </Button>
                {resume.match_score !== null && (
                  <div className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
                    当前匹配度：<span className="font-bold">{resume.match_score}</span>
                  </div>
                )}
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
                <ResumeStructuredPreview value={normalizeResumeData(displayData || {})} />
                <details className="rounded-lg border border-slate-200 bg-white p-4">
                  <summary className="cursor-pointer text-sm font-semibold text-slate-700">查看原始结构化 JSON</summary>
                  <pre className="data-panel mt-4">{JSON.stringify(displayData || {}, null, 2)}</pre>
                </details>
              </div>
            )}
          </Card>
        </div>
      </div>
    </AppShell>
  )
}
