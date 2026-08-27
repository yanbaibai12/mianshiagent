import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router'
import {
  ArrowLeft,
  Check,
  ChevronRight,
  ClipboardCheck,
  Download,
  FileDiff,
  FileText,
  Gauge,
  History,
  Play,
  RefreshCcw,
  RotateCcw,
  SearchCheck,
  ShieldCheck,
  Target,
  XCircle,
} from 'lucide-react'
import AppShell from '../components/AppShell'
import { ResumePaperPreview, type ResumeData } from '../components/ResumeStructuredEditor'
import { Badge, Button, EmptyState, LoadingState, ProgressBar, cn } from '../components/ui'
import { interviewApi } from '../services/interview'
import { jobsApi, type ApplicationReview, type JobApplication } from '../services/jobs'
import { resumeApi, type AtsReport, type Resume, type ResumeVersion } from '../services/resume'
import { taskApi, type AsyncTask } from '../services/tasks'

type WorkspaceStage = 'diagnosis' | 'optimization' | 'delivery'

type ChangeDetail = {
  section?: string
  before?: string
  after?: string
  reason?: string
  evidence?: string
}

const workspaceStages: Array<{
  id: WorkspaceStage
  index: string
  label: string
  caption: string
}> = [
  { id: 'diagnosis', index: '01', label: '岗位诊断', caption: '要求与差距' },
  { id: 'optimization', index: '02', label: '简历优化', caption: '修改与预览' },
  { id: 'delivery', index: '03', label: '投递准备', caption: '版本与训练' },
]

const changeSectionLabels: Record<string, string> = {
  personal: '基本信息',
  education: '教育背景',
  experience: '工作 / 实习经历',
  projects: '项目经历',
  project: '项目经历',
  skills: '技能关键词',
  summary: '个人总结',
}

const jobStatusLabels: Record<string, string> = {
  draft: '待优化',
  optimizing: '优化中',
  optimized: '已优化',
  interviewing: '面试训练中',
  reported: '已完成',
}

const versionTypeLabels: Record<string, string> = {
  original: '原始版',
  optimized: '优化版',
  jd_adapted: '岗位优化版',
  delivery: '投递版',
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

function scoreTone(score: number): 'success' | 'warning' | 'danger' {
  if (score >= 80) return 'success'
  if (score >= 65) return 'warning'
  return 'danger'
}

function applicationReviewFromJob(job: JobApplication | null): ApplicationReview | null {
  const review = job?.ats_report?.application_review
  return review && typeof review === 'object' ? review as ApplicationReview : null
}

function reviewTone(review: ApplicationReview | null): 'success' | 'warning' | 'danger' | 'info' | 'neutral' {
  if (!review) return 'neutral'
  if (review.decision === 'apply_now') return 'success'
  if (review.decision === 'revise_before_apply') return 'warning'
  if (review.decision === 'low_priority') return 'info'
  return 'danger'
}

function changeSectionLabel(section?: string) {
  if (!section) return '简历内容'
  return changeSectionLabels[section] || section
}

function asChangeDetails(value: unknown): ChangeDetail[] {
  if (!Array.isArray(value)) return []
  return value.filter((item): item is ChangeDetail => Boolean(item) && typeof item === 'object')
}

function formatDate(value: string) {
  return new Date(value).toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })
}

function WorkspaceTabs({ active, onChange }: { active: WorkspaceStage; onChange: (stage: WorkspaceStage) => void }) {
  return (
    <div className="grid grid-cols-3 overflow-hidden rounded-lg border border-slate-200 bg-white" role="tablist" aria-label="岗位适配阶段">
      {workspaceStages.map((stage, index) => {
        const selected = stage.id === active
        return (
          <button
            key={stage.id}
            type="button"
            role="tab"
            aria-selected={selected}
            onClick={() => onChange(stage.id)}
            className={cn(
              'group flex min-h-16 items-center gap-2 border-r border-slate-200 px-2 text-left transition last:border-r-0 sm:min-h-[72px] sm:gap-3 sm:px-4',
              selected ? 'bg-slate-950 text-white' : 'bg-white text-slate-700 hover:bg-slate-50',
            )}
          >
            <span className="hidden text-xs font-bold text-slate-400 sm:inline">{stage.index}</span>
            <span className="min-w-0 flex-1">
              <span className="block text-sm font-semibold">{stage.label}</span>
              <span className={cn('mt-0.5 hidden text-xs sm:block', selected ? 'text-slate-400' : 'text-slate-500')}>{stage.caption}</span>
            </span>
            {index < workspaceStages.length - 1 && <ChevronRight size={16} className={cn('hidden shrink-0 lg:block', selected ? 'text-slate-500' : 'text-slate-300')} />}
          </button>
        )
      })}
    </div>
  )
}

function ApplicationReviewPanel({ review }: { review: ApplicationReview | null }) {
  if (!review) {
    return (
      <EmptyState
        title="尚未完成投递预审"
        description="运行预审后，这里会给出投递优先级、已有优势和需要先处理的阻塞点。"
        icon={<ClipboardCheck size={20} />}
      />
    )
  }

  const groups = [
    { label: '可用优势', items: review.strengths || [], tone: 'emerald' },
    { label: '关键缺口', items: review.blockers || [], tone: 'rose' },
    { label: '投递前动作', items: review.actions_before_apply || [], tone: 'amber' },
  ] as const

  return (
    <div data-testid="application-review-panel">
      <div className="flex flex-col justify-between gap-5 border-b border-slate-200 pb-6 lg:flex-row lg:items-start">
        <div className="max-w-3xl">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <Badge tone={reviewTone(review)}>{review.decision_label}</Badge>
            <Badge tone="neutral">{review.priority === 'high' ? '高优先级' : review.priority === 'medium' ? '中优先级' : review.priority === 'low' ? '低优先级' : '暂缓'}</Badge>
          </div>
          <p className="text-sm leading-7 text-slate-700">{review.summary}</p>
        </div>
        <div className="flex shrink-0 items-end gap-2">
          <span className="text-4xl font-bold text-slate-950">{review.score}</span>
          <span className="pb-1 text-sm text-slate-500">投递分 / 100</span>
        </div>
      </div>

      <div className="grid border-b border-slate-200 md:grid-cols-3">
        {groups.map((group, groupIndex) => (
          <div key={group.label} className={cn('py-5 md:px-5', groupIndex > 0 && 'border-t border-slate-200 md:border-l md:border-t-0', groupIndex === 0 && 'md:pl-0', groupIndex === groups.length - 1 && 'md:pr-0')}>
            <div className="mb-3 text-xs font-bold text-slate-500">{group.label}</div>
            <ul className="space-y-2 text-sm leading-6 text-slate-700">
              {group.items.slice(0, 5).map((item) => (
                <li key={item} className="flex gap-2">
                  <span className={cn('mt-2 h-1.5 w-1.5 shrink-0 rounded-full', group.tone === 'emerald' && 'bg-emerald-500', group.tone === 'rose' && 'bg-rose-500', group.tone === 'amber' && 'bg-amber-500')} />
                  <span>{item}</span>
                </li>
              ))}
              {group.items.length === 0 && <li className="text-slate-400">暂无明确项</li>}
            </ul>
          </div>
        ))}
      </div>

      {review.reviewer_checks?.length > 0 && (
        <div className="grid gap-x-8 gap-y-4 pt-5 md:grid-cols-3">
          {review.reviewer_checks.map((item) => (
            <div key={item.name}>
              <div className="mb-1.5 flex items-center gap-2">
                <span className={cn('flex h-5 w-5 items-center justify-center rounded-full', item.status === 'pass' ? 'bg-emerald-100 text-emerald-700' : item.status === 'warning' ? 'bg-amber-100 text-amber-700' : 'bg-slate-100 text-slate-500')}>
                  <Check size={12} strokeWidth={3} />
                </span>
                <span className="text-sm font-semibold text-slate-900">{item.name}</span>
              </div>
              <p className="pl-7 text-xs leading-5 text-slate-500">{item.detail}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function AtsPanel({ report }: { report: AtsReport | null }) {
  if (!report) {
    return <EmptyState title="暂无 ATS 评分" description="生成岗位优化版后，将按技能、项目证据和关键词覆盖给出逐项匹配分析。" icon={<Gauge size={20} />} />
  }

  return (
    <div data-testid="ats-panel">
      <div className="mb-5 flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
        <div>
          <h3 className="text-base font-semibold text-slate-950">ATS / JD 匹配</h3>
          <p className="mt-1 text-sm text-slate-500">每一分都对应可回查的简历证据或岗位缺口。</p>
        </div>
        <div className="flex items-baseline gap-1">
          <span className="text-3xl font-bold text-slate-950">{report.total_score}</span>
          <span className="text-xs text-slate-500">/ 100</span>
        </div>
      </div>
      <div className="grid gap-x-8 gap-y-5 md:grid-cols-2 xl:grid-cols-3">
        {(report.dimensions || []).map((dimension) => (
          <div key={dimension.key} className="border-t border-slate-200 pt-4">
            <div className="mb-2 flex items-center justify-between gap-2">
              <div className="text-sm font-semibold text-slate-900">{dimension.name}</div>
              <Badge tone={scoreTone(Number(dimension.score || 0))}>{dimension.score}</Badge>
            </div>
            <ProgressBar value={Number(dimension.score || 0)} />
            {dimension.covered?.length ? <p className="mt-3 text-xs leading-5 text-emerald-700">已覆盖：{dimension.covered.slice(0, 3).join('、')}</p> : null}
            {dimension.missing?.length ? <p className="mt-1.5 text-xs leading-5 text-rose-700">待补齐：{dimension.missing.slice(0, 3).join('、')}</p> : null}
            {dimension.suggestion && <p className="mt-1.5 text-xs leading-5 text-slate-500">{dimension.suggestion}</p>}
          </div>
        ))}
      </div>
    </div>
  )
}

function JobContextPanel({ job }: { job: JobApplication }) {
  return (
    <aside className="xl:sticky xl:top-6 xl:self-start">
      <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
        <div className="border-b border-slate-200 px-5 py-4">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="text-xs font-semibold text-slate-500">目标岗位</div>
              <h2 className="mt-1 truncate text-base font-semibold text-slate-950">{job.title}</h2>
              <p className="mt-1 text-sm text-slate-500">{job.company || '公司未填写'}</p>
            </div>
            <Badge tone={job.resume_id ? 'success' : 'warning'}>{job.resume_id ? '已绑定简历' : '未绑定'}</Badge>
          </div>
        </div>
        <div className="px-5 py-4">
          <div className="mb-3 flex items-center justify-between">
            <span className="text-xs font-bold text-slate-500">岗位描述</span>
            <span className="text-xs text-slate-400">{job.jd_text.length.toLocaleString()} 字</span>
          </div>
          <div className="max-h-[560px] overflow-y-auto whitespace-pre-wrap pr-2 text-sm leading-7 text-slate-700">
            {job.jd_text}
          </div>
        </div>
      </div>
    </aside>
  )
}

function ChangeList({ changes }: { changes: ChangeDetail[] }) {
  if (changes.length === 0) {
    return (
      <EmptyState
        title="还没有岗位定向修改"
        description="生成优化版后，系统会逐条展示修改前、修改后、原因和原简历证据。"
        icon={<FileDiff size={20} />}
      />
    )
  }

  return (
    <div className="space-y-4" data-testid="job-change-details">
      {changes.map((change, index) => (
        <article key={`${change.section}-${index}`} className="overflow-hidden rounded-lg border border-slate-200 bg-white">
          <div className="flex items-center justify-between border-b border-slate-200 bg-slate-50 px-4 py-3">
            <div className="flex items-center gap-2">
              <span className="flex h-6 w-6 items-center justify-center rounded bg-slate-900 text-xs font-bold text-white">{index + 1}</span>
              <span className="text-sm font-semibold text-slate-900">{changeSectionLabel(change.section)}</span>
            </div>
            <Badge tone="neutral">已改写</Badge>
          </div>
          <div className="grid md:grid-cols-2">
            <div className="border-b border-slate-200 p-4 md:border-b-0 md:border-r">
              <div className="mb-2 text-xs font-bold text-slate-400">修改前</div>
              <p className="text-sm leading-6 text-slate-500 line-through decoration-slate-300">{change.before || '原文未单独成句'}</p>
            </div>
            <div className="bg-emerald-50/40 p-4">
              <div className="mb-2 text-xs font-bold text-emerald-700">修改后</div>
              <p className="text-sm font-medium leading-6 text-slate-800">{change.after || '暂无修改结果'}</p>
            </div>
          </div>
          {(change.reason || change.evidence) && (
            <div className="space-y-1.5 border-t border-slate-200 px-4 py-3 text-xs leading-5 text-slate-600">
              {change.reason && <p><span className="font-semibold text-slate-800">修改原因：</span>{change.reason}</p>}
              {change.evidence && <p><span className="font-semibold text-slate-800">原始证据：</span>{change.evidence}</p>}
            </div>
          )}
        </article>
      ))}
    </div>
  )
}

export default function JobDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [job, setJob] = useState<JobApplication | null>(null)
  const [resume, setResume] = useState<Resume | null>(null)
  const [versions, setVersions] = useState<ResumeVersion[]>([])
  const [activeStage, setActiveStage] = useState<WorkspaceStage>('diagnosis')
  const [activeTask, setActiveTask] = useState<AsyncTask | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  const atsReport = useMemo(() => {
    const report = job?.ats_report
    return report && Array.isArray((report as AtsReport).dimensions) ? report as AtsReport : null
  }, [job])

  const applicationReview = useMemo(() => applicationReviewFromJob(job), [job])

  const currentVersion = useMemo(() => {
    if (!job?.current_resume_version_id) return null
    return versions.find((version) => version.id === job.current_resume_version_id) || null
  }, [job?.current_resume_version_id, versions])

  const changeDetails = useMemo(() => {
    if (!job?.current_resume_version_id) return []
    const versionChanges = asChangeDetails(currentVersion?.change_details)
    if (versionChanges.length > 0) return versionChanges
    return asChangeDetails(resume?.optimized_data?.change_details)
  }, [currentVersion, job?.current_resume_version_id, resume])

  const previewData = useMemo(() => {
    return (currentVersion?.data || resume?.optimized_data || resume?.parsed_data || {}) as ResumeData
  }, [currentVersion, resume])

  const missingRequirements = useMemo(() => {
    const values = [
      ...(atsReport?.missing_top || []),
      ...(atsReport?.dimensions || []).flatMap((dimension) => dimension.missing || []),
    ].filter(Boolean)
    return Array.from(new Set(values)).slice(0, 8)
  }, [atsReport])

  const loadJob = async () => {
    if (!id) return
    setError('')
    const jobResponse = await jobsApi.get(id)
    setJob(jobResponse.data)

    if (!jobResponse.data.resume_id) {
      setResume(null)
      setVersions([])
      return
    }

    try {
      const [resumeResponse, versionResponse] = await Promise.all([
        resumeApi.get(jobResponse.data.resume_id),
        resumeApi.versions(jobResponse.data.resume_id),
      ])
      setResume(resumeResponse.data)
      setVersions(versionResponse.data)
    } catch {
      setResume(null)
      setVersions([])
    }
  }

  useEffect(() => {
    loadJob().catch((err: any) => setError(err.response?.data?.detail || '岗位详情加载失败')).finally(() => setLoading(false))
  }, [id])

  const pollTask = async (task: AsyncTask) => {
    setActiveTask(task)
    let current = task
    while (!['success', 'failed', 'cancelled'].includes(current.status)) {
      await new Promise((resolve) => window.setTimeout(resolve, 1500))
      current = (await taskApi.get(current.id)).data
      setActiveTask(current)
    }
    return current
  }

  const runAdapt = async () => {
    if (!job) return
    setBusy(true)
    setError('')
    setMessage('')
    try {
      const created = await jobsApi.adaptResumeTask(job.id)
      const task = await pollTask(created.data.task)
      if (task.status !== 'success') throw new Error(task.error_message || '岗位优化失败')
      await loadJob()
      setMessage('岗位简历优化已完成，已生成当前简历版本。')
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || '岗位优化失败')
    } finally {
      setBusy(false)
      setActiveTask(null)
    }
  }

  const runPreflight = async () => {
    if (!job) return
    setBusy(true)
    setError('')
    setMessage('')
    try {
      const response = await jobsApi.preflight(job.id)
      setJob(response.data)
      setMessage('投递预审已完成。')
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || '投递预审失败')
    } finally {
      setBusy(false)
    }
  }

  const retryTask = async () => {
    if (!activeTask) return
    setError('')
    const task = (await taskApi.retry(activeTask.id)).data
    const result = await pollTask(task)
    if (result.status === 'success') {
      await loadJob()
      setMessage('任务重试成功。')
      setActiveTask(null)
    }
  }

  const cancelTask = async () => {
    if (!activeTask) return
    const task = (await taskApi.cancel(activeTask.id)).data
    setActiveTask(task)
  }

  const exportResume = async () => {
    if (!job) return
    setBusy(true)
    setError('')
    try {
      const response = await jobsApi.exportDeliveryResume(job.id)
      downloadBlob(response.data, `${job.company ? `${job.company}-` : ''}${job.title}-投递版简历.docx`)
      setMessage('投递版简历 Word 已生成。')
    } catch (err: any) {
      setError(err.response?.data?.detail || '投递版导出失败')
    } finally {
      setBusy(false)
    }
  }

  const startInterview = async () => {
    if (!job) return
    setBusy(true)
    setError('')
    try {
      const interview = job.interview_id ? { id: job.interview_id } : (await jobsApi.createInterview(job.id)).data
      try {
        await interviewApi.generateQuestions(interview.id)
      } catch {
        // 面试页仍可手动生成或重建题库。
      }
      navigate(`/interviews/${interview.id}`)
    } catch (err: any) {
      setError(err.response?.data?.detail || '创建岗位面试失败')
    } finally {
      setBusy(false)
    }
  }

  if (loading) return <LoadingState label="正在加载岗位任务" />

  if (!job) {
    return (
      <AppShell title="岗位任务" actions={<Button type="button" variant="secondary" onClick={() => navigate('/jobs')}>返回</Button>}>
        <EmptyState title="岗位任务不可用" description={error || '请返回岗位工作台重新选择。'} />
      </AppShell>
    )
  }

  return (
    <AppShell
      title={`${job.company ? `${job.company} · ` : ''}${job.title}`}
      description="岗位适配工作区"
      contentWidth="wide"
      actions={
        <>
          <Button type="button" variant="secondary" onClick={() => navigate('/jobs')}>
            <ArrowLeft size={16} />
            返回岗位
          </Button>
          {job.resume_id && (
            <Button type="button" variant="secondary" onClick={() => navigate(`/resumes/${job.resume_id}`)}>
              <FileText size={16} />
              简历版本
            </Button>
          )}
          <Button type="button" onClick={runAdapt} disabled={busy || !job.resume_id} data-testid="job-adapt-button">
            <RefreshCcw size={16} />
            {busy ? '处理中...' : job.current_resume_version_id ? '重新优化' : '生成优化版'}
          </Button>
        </>
      }
    >
      <div className="space-y-5">
        {error && <div className="rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div>}
        {message && <div className="rounded-md border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{message}</div>}

        {activeTask && (
          <section className="rounded-lg border border-slate-200 bg-white p-5" data-testid="job-task-progress">
            <div className="mb-3 flex flex-col justify-between gap-3 lg:flex-row lg:items-center">
              <div>
                <div className="font-semibold text-slate-950">{activeTask.stage}</div>
                <div className="mt-1 text-xs text-slate-500">{activeTask.queue_backend} · {activeTask.queue_name}</div>
              </div>
              <div className="flex items-center gap-2">
                <Badge tone={activeTask.status === 'failed' ? 'danger' : activeTask.status === 'success' ? 'success' : 'info'}>{activeTask.status}</Badge>
                <Badge tone="neutral">{activeTask.progress}%</Badge>
              </div>
            </div>
            <ProgressBar value={activeTask.progress} />
            <div className="mt-3 flex flex-wrap gap-2">
              {activeTask.status === 'failed' && activeTask.retry_count < activeTask.max_retries && (
                <Button type="button" size="sm" variant="secondary" onClick={retryTask}><RotateCcw size={14} />重试</Button>
              )}
              {!['success', 'failed', 'cancelled'].includes(activeTask.status) && (
                <Button type="button" size="sm" variant="danger" onClick={cancelTask}><XCircle size={14} />取消</Button>
              )}
            </div>
          </section>
        )}

        <section className="overflow-hidden rounded-lg border border-slate-200 bg-white">
          <div className="grid divide-y divide-slate-200 sm:grid-cols-2 sm:divide-x sm:divide-y-0 xl:grid-cols-4">
            <div className="px-5 py-4">
              <div className="text-xs font-semibold text-slate-500">当前阶段</div>
              <div className="mt-1 flex items-center gap-2 text-sm font-bold text-slate-950"><Target size={15} />{jobStatusLabels[job.status] || job.status}</div>
            </div>
            <div className="px-5 py-4">
              <div className="text-xs font-semibold text-slate-500">岗位匹配</div>
              <div className="mt-1 text-sm font-bold text-slate-950">{job.match_score ?? '待评估'}{job.match_score !== null ? ' / 100' : ''}</div>
            </div>
            <div className="px-5 py-4">
              <div className="text-xs font-semibold text-slate-500">简历版本</div>
              <div className="mt-1 text-sm font-bold text-slate-950">{currentVersion ? `v${currentVersion.version_number} · 当前` : '尚未生成'}</div>
            </div>
            <div className="px-5 py-4">
              <div className="text-xs font-semibold text-slate-500">最近更新</div>
              <div className="mt-1 text-sm font-bold text-slate-950">{formatDate(job.updated_at)}</div>
            </div>
          </div>
        </section>

        <WorkspaceTabs active={activeStage} onChange={setActiveStage} />

        {activeStage === 'diagnosis' && (
          <div className="grid gap-5 xl:grid-cols-[360px_minmax(0,1fr)]">
            <JobContextPanel job={job} />
            <div className="min-w-0 space-y-5">
              <section className="rounded-lg border border-slate-200 bg-white p-5 sm:p-6">
                <div className="mb-6 flex flex-col justify-between gap-4 border-b border-slate-200 pb-5 sm:flex-row sm:items-start">
                  <div>
                    <div className="mb-2 flex items-center gap-2 text-xs font-bold text-slate-500"><SearchCheck size={15} />岗位诊断</div>
                    <h2 className="text-lg font-bold text-slate-950">这份岗位值得投吗？</h2>
                    <p className="mt-1.5 text-sm leading-6 text-slate-500">先判断证据覆盖和投递优先级，再决定简历优化投入。</p>
                  </div>
                  <Button type="button" variant="secondary" onClick={runPreflight} disabled={busy || !job.resume_id}>
                    <ClipboardCheck size={16} />{applicationReview ? '重新预审' : '运行投递预审'}
                  </Button>
                </div>
                <ApplicationReviewPanel review={applicationReview} />
              </section>

              <section className="rounded-lg border border-slate-200 bg-white p-5 sm:p-6">
                <AtsPanel report={atsReport} />
              </section>
            </div>
          </div>
        )}

        {activeStage === 'optimization' && (
          <div className="grid items-start gap-5 xl:grid-cols-[minmax(380px,0.86fr)_minmax(520px,1.14fr)]">
            <div className="min-w-0 space-y-5">
              <section className="rounded-lg border border-slate-200 bg-white p-5">
                <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-start">
                  <div>
                    <div className="mb-2 flex items-center gap-2 text-xs font-bold text-slate-500"><FileDiff size={15} />岗位定向修改</div>
                    <h2 className="text-lg font-bold text-slate-950">修改清单</h2>
                    <p className="mt-1.5 text-sm text-slate-500">{changeDetails.length > 0 ? `${changeDetails.length} 处改动，全部保留原始证据。` : '当前还没有可对照的优化结果。'}</p>
                  </div>
                  <Button type="button" onClick={runAdapt} disabled={busy || !job.resume_id}>
                    <RefreshCcw size={16} />{job.current_resume_version_id ? '重新生成' : '生成优化版'}
                  </Button>
                </div>
              </section>

              {missingRequirements.length > 0 && (
                <section className="rounded-lg border border-slate-200 bg-white p-5">
                  <div className="mb-4 flex items-center justify-between gap-3">
                    <h3 className="text-sm font-semibold text-slate-950">待补齐要求</h3>
                    <Badge tone="warning">{missingRequirements.length} 项</Badge>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {missingRequirements.map((item) => <Badge key={item} tone="neutral">{item}</Badge>)}
                  </div>
                  <p className="mt-4 text-xs leading-5 text-slate-500">缺少原始证据的要求不会被写进简历正文。</p>
                </section>
              )}

              <ChangeList changes={changeDetails} />
            </div>

            <aside className="min-w-0 xl:sticky xl:top-6 xl:self-start">
              <section className="overflow-hidden rounded-lg border border-slate-200 bg-slate-100">
                <div className="flex flex-col justify-between gap-3 border-b border-slate-200 bg-white px-5 py-4 sm:flex-row sm:items-center">
                  <div>
                    <div className="flex items-center gap-2">
                      <h2 className="text-sm font-semibold text-slate-950">投递版预览</h2>
                      {currentVersion && <Badge tone="success">v{currentVersion.version_number}</Badge>}
                    </div>
                    <p className="mt-1 text-xs text-slate-500">{resume?.title || '当前绑定简历'}</p>
                  </div>
                  {job.resume_id && (
                    <Button type="button" variant="secondary" size="sm" onClick={() => navigate(`/resumes/${job.resume_id}`)}>
                      <FileText size={14} />编辑原始内容
                    </Button>
                  )}
                </div>
                <div className="max-h-none overflow-auto p-3 sm:p-5 xl:max-h-[calc(100vh-150px)]">
                  {resume ? <ResumePaperPreview value={previewData} /> : <EmptyState title="简历预览不可用" description="请检查当前岗位绑定的简历。" />}
                </div>
              </section>
            </aside>
          </div>
        )}

        {activeStage === 'delivery' && (
          <div className="min-w-0">
            <div className="space-y-5">
              <section className="rounded-lg border border-slate-200 bg-white p-5 sm:p-6">
                <div className="mb-6 flex items-start justify-between gap-4">
                  <div>
                    <div className="mb-2 flex items-center gap-2 text-xs font-bold text-slate-500"><ShieldCheck size={15} />投递准备</div>
                    <h2 className="text-lg font-bold text-slate-950">完成最后检查</h2>
                  </div>
                  <Badge tone={job.current_resume_version_id ? 'success' : 'warning'}>{job.current_resume_version_id ? '投递版已就绪' : '等待优化版'}</Badge>
                </div>

                <div className="divide-y divide-slate-200 border-y border-slate-200">
                  {[
                    { label: '岗位与简历已绑定', done: Boolean(job.resume_id), detail: resume?.title || '需要先绑定简历' },
                    { label: '岗位匹配已评估', done: Boolean(atsReport), detail: atsReport ? `当前 ${atsReport.total_score} 分` : '尚无 ATS 结果' },
                    { label: '岗位定向版本已生成', done: Boolean(currentVersion), detail: currentVersion ? `v${currentVersion.version_number} · ${currentVersion.title}` : '尚未生成' },
                    { label: '岗位面试已创建', done: Boolean(job.interview_id), detail: job.interview_id ? '可继续训练' : '导出后可开始训练' },
                  ].map((item) => (
                    <div key={item.label} className="flex items-start gap-3 py-4">
                      <span className={cn('mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full', item.done ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-400')}>
                        <Check size={14} strokeWidth={3} />
                      </span>
                      <div className="min-w-0">
                        <div className="text-sm font-semibold text-slate-900">{item.label}</div>
                        <div className="mt-1 text-xs text-slate-500">{item.detail}</div>
                      </div>
                    </div>
                  ))}
                </div>

                <div className="mt-6 grid gap-3 sm:grid-cols-2">
                  <Button type="button" onClick={exportResume} disabled={busy || !job.current_resume_version_id} data-testid="export-delivery-resume-button">
                    <Download size={16} />导出投递版 Word
                  </Button>
                  <Button type="button" variant="success" onClick={startInterview} disabled={busy || !job.resume_id} data-testid="start-job-interview-button">
                    <Play size={16} />{job.interview_id ? '继续岗位面试' : '开始岗位面试'}
                  </Button>
                  {job.interview_id && (
                    <Button type="button" variant="secondary" onClick={() => navigate(`/reports/${job.interview_id}`)}>
                      <FileText size={16} />查看面试报告
                    </Button>
                  )}
                  {job.resume_id && (
                    <Button type="button" variant="secondary" onClick={() => navigate(`/resumes/${job.resume_id}`)}>
                      <History size={16} />管理全部版本
                    </Button>
                  )}
                </div>
              </section>

              <section className="rounded-lg border border-slate-200 bg-white p-5 sm:p-6">
                <div className="mb-5 flex items-center justify-between gap-3">
                  <div>
                    <h2 className="text-base font-semibold text-slate-950">版本记录</h2>
                    <p className="mt-1 text-sm text-slate-500">岗位优化不会覆盖历史版本。</p>
                  </div>
                  <Badge tone="neutral">{versions.length} 版</Badge>
                </div>
                <div className="divide-y divide-slate-200 border-y border-slate-200">
                  {versions.slice(0, 5).map((version) => (
                    <div key={version.id} className="flex flex-col justify-between gap-3 py-4 sm:flex-row sm:items-center">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-sm font-semibold text-slate-900">v{version.version_number} · {version.title}</span>
                          {version.id === job.current_resume_version_id && <Badge tone="success">当前岗位</Badge>}
                        </div>
                        <div className="mt-1 text-xs text-slate-500">{new Date(version.created_at).toLocaleString('zh-CN')} · {version.change_details?.length || 0} 处改动</div>
                      </div>
                      <Badge tone={version.version_type === 'delivery' ? 'success' : version.version_type === 'original' ? 'neutral' : 'info'}>{versionTypeLabels[version.version_type] || version.version_type}</Badge>
                    </div>
                  ))}
                  {versions.length === 0 && <div className="py-8 text-center text-sm text-slate-500">暂无版本记录</div>}
                </div>
              </section>
            </div>

          </div>
        )}
      </div>
    </AppShell>
  )
}
