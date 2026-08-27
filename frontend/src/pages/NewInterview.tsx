import { useEffect, useState } from 'react'
import { useSearchParams, useNavigate } from 'react-router'
import { ArrowLeft, Check, FileText, Layers3, MessageSquareText, Play, Target } from 'lucide-react'
import AppShell from '../components/AppShell'
import { Button, EmptyState, Field, LoadingState } from '../components/ui'
import { interviewApi, type InterviewTemplate } from '../services/interview'
import { resumeApi, type Resume, type ResumeSummary } from '../services/resume'
import { SAMPLE_JD_TEXT } from '../data/examples'

const DEFAULT_TEMPLATE_ID = 'comprehensive'

const moduleLabels: Record<string, string> = {
  project: '项目',
  internship: '实习',
  agent_fundamentals: 'Agent 八股',
  system_design: '系统设计',
  behavioral: '行为面',
  resume: '简历',
}

export default function NewInterviewPage() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const initialResumeId = searchParams.get('resumeId') || ''
  const initialCompany = searchParams.get('company') || ''
  const initialPosition = searchParams.get('position') || ''
  const [resumes, setResumes] = useState<ResumeSummary[]>([])
  const [selectedResumeDetail, setSelectedResumeDetail] = useState<Resume | null>(null)
  const [templates, setTemplates] = useState<InterviewTemplate[]>([])
  const [templateId, setTemplateId] = useState(DEFAULT_TEMPLATE_ID)
  const [resumeId, setResumeId] = useState(initialResumeId)
  const [jdText, setJdText] = useState('')
  const [targetCompany, setTargetCompany] = useState(initialCompany)
  const [targetPosition, setTargetPosition] = useState(initialPosition)
  const [autoJdResumeId, setAutoJdResumeId] = useState<string | null>(null)
  const [jdManuallyEdited, setJdManuallyEdited] = useState(false)
  const [loading, setLoading] = useState(false)
  const [loadingLabel, setLoadingLabel] = useState('')
  const [loadingResumes, setLoadingResumes] = useState(true)
  const [loadingResumeDetail, setLoadingResumeDetail] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    Promise.all([resumeApi.list(), interviewApi.templates()])
      .then(([res, templateRes]) => {
        setResumes(res.data)
        setTemplates(templateRes.data)
        if (!templateRes.data.some((template) => template.template_id === templateId)) {
          setTemplateId(DEFAULT_TEMPLATE_ID)
        }
        if (!initialResumeId && res.data.length > 0) {
          setResumeId(res.data[0].id)
        }
      })
      .catch((err: any) => setError(err.response?.data?.detail || '简历列表加载失败'))
      .finally(() => setLoadingResumes(false))
  }, [initialResumeId])

  useEffect(() => {
    if (!resumeId) {
      setSelectedResumeDetail(null)
      return
    }
    let cancelled = false
    setLoadingResumeDetail(true)
    resumeApi.get(resumeId)
      .then((res) => {
        if (cancelled) return
        setSelectedResumeDetail(res.data)
        const recentJd = (res.data.jd_text || '').trim()
        if (recentJd && (!jdText.trim() || !jdManuallyEdited || autoJdResumeId)) {
          setJdText(recentJd)
          setAutoJdResumeId(resumeId)
          setJdManuallyEdited(false)
        }
      })
      .catch((err: any) => setError(err.response?.data?.detail || '简历详情加载失败'))
      .finally(() => {
        if (!cancelled) setLoadingResumeDetail(false)
      })
    return () => {
      cancelled = true
    }
  }, [resumeId])

  const selectedResume = resumes.find((resume) => resume.id === resumeId)
  const selectedTemplate = templates.find((template) => template.template_id === templateId)
  const recentJd = (selectedResumeDetail?.jd_text || '').trim()
  const usingRecentJd = Boolean(recentJd && autoJdResumeId === resumeId && jdText.trim() === recentJd)
  const handleUseRecentJd = () => {
    if (!recentJd || !resumeId) return
    setJdText(recentJd)
    setAutoJdResumeId(resumeId)
    setJdManuallyEdited(false)
  }

  const handleStart = async () => {
    if (!resumeId) {
      setError('请先选择简历')
      return
    }
    setLoading(true)
    setLoadingLabel('正在创建面试...')
    setError('')
    try {
      const res = await interviewApi.create(
        resumeId,
        jdText.trim() || undefined,
        templateId,
        targetCompany.trim() || undefined,
        targetPosition.trim() || undefined,
      )
      setLoadingLabel('正在生成题目...')
      try {
        await interviewApi.generateQuestions(res.data.id)
      } catch {
        // 进入面试页后仍可手动重试生成题目。
      }
      navigate(`/interviews/${res.data.id}`)
    } catch (err: any) {
      setError(err.response?.data?.detail || '创建面试失败')
    } finally {
      setLoading(false)
      setLoadingLabel('')
    }
  }

  if (loadingResumes) return <LoadingState label="正在准备面试配置" />

  return (
    <AppShell
      title="创建模拟面试"
      description="选择简历、面试轮次和目标岗位，然后开始练习。"
      actions={
        <Button type="button" variant="secondary" onClick={() => navigate('/resumes')}>
          <ArrowLeft size={16} />
          返回工作台
        </Button>
      }
    >
      <div className="mx-auto max-w-6xl space-y-6">
        {error && <div className="rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div>}

        {resumes.length === 0 ? (
          <EmptyState
            title="还没有可用于面试的简历"
            description="先上传并解析一份简历，再开始模拟面试。"
            action={
              <Button type="button" onClick={() => navigate('/resumes')}>
                上传简历
              </Button>
            }
          />
        ) : (
          <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
            <div className="space-y-5">
              <ol className="grid grid-cols-3 overflow-hidden rounded-lg border border-slate-200 bg-white" aria-label="面试配置步骤">
                {[
                  { number: 1, label: '选择简历', done: Boolean(resumeId) },
                  { number: 2, label: '选择轮次', done: Boolean(templateId) },
                  { number: 3, label: '补充岗位', done: Boolean(targetCompany || targetPosition || jdText) },
                ].map((step) => (
                  <li key={step.number} className="flex min-w-0 items-center gap-2 border-r border-slate-200 px-3 py-3 last:border-r-0 sm:px-4">
                    <span className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-bold ${step.done ? 'bg-emerald-700 text-white' : 'bg-slate-100 text-slate-500'}`}>
                      {step.done ? <Check size={13} /> : step.number}
                    </span>
                    <span className="truncate text-xs font-semibold text-slate-700 sm:text-sm">{step.label}</span>
                  </li>
                ))}
              </ol>

              <section className="workspace-panel">
                <div className="workspace-panel-header flex items-start gap-3">
                  <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-slate-900 text-xs font-bold text-white">1</span>
                  <div>
                    <h2 className="font-semibold text-slate-950">面试简历</h2>
                    <p className="mt-1 text-sm text-slate-500">题目会优先引用这份简历中的项目和经历。</p>
                  </div>
                </div>
                <div className="workspace-panel-body space-y-4">
                  <Field label="选择简历">
                    <select value={resumeId} onChange={(event) => setResumeId(event.target.value)} className="select">
                      <option value="">请选择</option>
                      {resumes.map((resume) => <option key={resume.id} value={resume.id}>{resume.title}</option>)}
                    </select>
                  </Field>
                  {selectedResume && (
                    <div className="flex flex-col justify-between gap-3 rounded-md border border-slate-200 bg-slate-50 px-4 py-3 sm:flex-row sm:items-center">
                      <div className="flex min-w-0 items-center gap-3">
                        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-white text-slate-600 ring-1 ring-slate-200"><FileText size={17} /></span>
                        <div className="min-w-0">
                          <div className="truncate text-sm font-semibold text-slate-950">{selectedResume.title}</div>
                          <div className="mt-0.5 text-xs text-slate-500">{selectedResume.template_id ? `版本 ${selectedResume.template_id}` : '原始简历'}{selectedResume.match_score ? ` · 匹配 ${selectedResume.match_score}` : ''}</div>
                        </div>
                      </div>
                      {loadingResumeDetail && <span className="text-xs text-slate-500">读取最近 JD...</span>}
                    </div>
                  )}
                </div>
              </section>

              {templates.length > 0 && (
                <section className="workspace-panel">
                  <div className="workspace-panel-header flex items-start gap-3">
                    <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-slate-900 text-xs font-bold text-white">2</span>
                    <div>
                      <h2 className="font-semibold text-slate-950">面试轮次</h2>
                      <p className="mt-1 text-sm text-slate-500">不同轮次使用不同题目来源和评分重点。</p>
                    </div>
                  </div>
                  <div className="workspace-panel-body grid gap-3 md:grid-cols-2">
                    {templates.map((template) => {
                      const active = template.template_id === templateId
                      const moduleFocus = Object.entries(template.module_question_limits || {})
                        .filter(([, count]) => count > 0)
                        .slice(0, 4)
                        .map(([module, count]) => `${moduleLabels[module] || module} ${count}`)
                        .join(' · ')
                      return (
                        <button
                          key={template.template_id}
                          type="button"
                          onClick={() => setTemplateId(template.template_id)}
                          className={`relative rounded-md border p-4 text-left transition ${active ? 'border-slate-800 bg-slate-50' : 'border-slate-200 bg-white hover:border-slate-400'}`}
                        >
                          <div className="flex items-start gap-3">
                            <span className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border ${active ? 'border-slate-900 bg-slate-900 text-white' : 'border-slate-300 bg-white'}`}>
                              {active && <Check size={12} />}
                            </span>
                            <div className="min-w-0">
                              <div className="font-semibold text-slate-950">{template.name}</div>
                              <p className="mt-1.5 text-sm leading-5 text-slate-600">{template.scenario}</p>
                              <div className="mt-3 text-xs leading-5 text-slate-500">{template.question_count} 题 · {moduleFocus}</div>
                            </div>
                          </div>
                        </button>
                      )
                    })}
                  </div>
                </section>
              )}

              <section className="workspace-panel">
                <div className="workspace-panel-header flex items-start gap-3">
                  <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-slate-900 text-xs font-bold text-white">3</span>
                  <div>
                    <h2 className="font-semibold text-slate-950">目标岗位</h2>
                    <p className="mt-1 text-sm text-slate-500">信息越具体，问题越贴近目标公司的实际面试。</p>
                  </div>
                </div>
                <div className="workspace-panel-body space-y-4">
                  <div className="grid gap-4 sm:grid-cols-2">
                    <Field label="目标公司" hint="可选，用于查找相关面经">
                      <input className="input" value={targetCompany} onChange={(event) => setTargetCompany(event.target.value)} placeholder="例如：字节跳动" maxLength={160} />
                    </Field>
                    <Field label="目标岗位" hint="可选，建议填写完整岗位名称">
                      <input className="input" value={targetPosition} onChange={(event) => setTargetPosition(event.target.value)} placeholder="例如：Agent 应用开发" maxLength={200} />
                    </Field>
                  </div>


                  {recentJd && (
                    <div className="flex flex-col justify-between gap-3 rounded-md border border-slate-200 bg-slate-50 px-4 py-3 sm:flex-row sm:items-center">
                      <div>
                        <div className="text-sm font-semibold text-slate-900">这份简历有最近使用的 JD</div>
                        <div className="mt-1 text-xs text-slate-500">{usingRecentJd ? '当前已经沿用' : '可以直接用于本轮面试'}</div>
                      </div>
                      {!usingRecentJd && <Button type="button" variant="secondary" size="sm" onClick={handleUseRecentJd}>使用该 JD</Button>}
                    </div>
                  )}

                  <Field label="岗位 JD" hint={`${jdText.length}/40000 字符，可选${usingRecentJd ? '，当前使用最近一次 JD' : ''}`}>
                    <textarea
                      placeholder="粘贴岗位职责和要求"
                      value={jdText}
                      onChange={(event) => {
                        setJdText(event.target.value)
                        setJdManuallyEdited(true)
                        setAutoJdResumeId(null)
                      }}
                      className="textarea min-h-48"
                      maxLength={40000}
                    />
                  </Field>
                </div>
              </section>
            </div>

            <aside className="space-y-3 lg:sticky lg:top-8">
              <div className="workspace-panel shadow-sm">
                <div className="workspace-panel-header">
                  <h2 className="font-semibold text-slate-950">本次面试</h2>
                  <p className="mt-1 text-sm text-slate-500">创建前确认本轮训练范围。</p>
                </div>
                <div className="workspace-panel-body space-y-4">
                  <div className="space-y-3 text-sm">
                    <div className="flex items-start gap-3"><FileText size={16} className="mt-0.5 shrink-0 text-slate-500" /><div><div className="text-xs text-slate-500">简历</div><div className="mt-0.5 font-medium text-slate-900">{selectedResume?.title || '未选择'}</div></div></div>
                    <div className="flex items-start gap-3"><Layers3 size={16} className="mt-0.5 shrink-0 text-slate-500" /><div><div className="text-xs text-slate-500">轮次</div><div className="mt-0.5 font-medium text-slate-900">{selectedTemplate?.name || '综合面'}</div></div></div>
                    <div className="flex items-start gap-3"><Target size={16} className="mt-0.5 shrink-0 text-slate-500" /><div><div className="text-xs text-slate-500">目标</div><div className="mt-0.5 font-medium text-slate-900">{[targetCompany, targetPosition].filter(Boolean).join(' · ') || '通用岗位训练'}</div></div></div>
                  </div>
                  {selectedTemplate && (
                    <div className="border-t border-slate-200 pt-4">
                      <div className="flex items-end justify-between"><span className="text-xs font-medium text-slate-500">预计题量</span><span className="text-xl font-bold text-slate-950">{selectedTemplate.question_count}</span></div>
                      <div className="mt-3 text-xs leading-5 text-slate-500">重点：{selectedTemplate.question_focus.slice(0, 4).join('、')}</div>
                    </div>
                  )}
                  <Button type="button" size="lg" className="w-full" onClick={handleStart} disabled={loading || !resumeId}>
                    {loading ? <MessageSquareText size={16} /> : <Play size={16} />}
                    {loading ? loadingLabel || '处理中...' : '开始生成面试'}
                  </Button>
                </div>
              </div>
              <Button type="button" variant="secondary" className="w-full" onClick={() => { setJdText(SAMPLE_JD_TEXT); setJdManuallyEdited(true); setAutoJdResumeId(null) }}>
                填入示例 JD
              </Button>
            </aside>
          </div>
        )}
      </div>
    </AppShell>
  )
}
