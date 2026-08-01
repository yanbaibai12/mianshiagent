import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router'
import { ArrowRight, CheckCircle2, ClipboardPaste, FileText, Plus, RefreshCcw, SearchCheck } from 'lucide-react'
import AppShell from '../components/AppShell'
import { Badge, Button, EmptyState, Field, LoadingState, ProgressBar } from '../components/ui'
import { jobsApi, type ApplicationReview, type JobApplication } from '../services/jobs'
import { resumeApi, type ResumeSummary } from '../services/resume'
import { taskApi, type AsyncTask } from '../services/tasks'
import { SAMPLE_COMPANY, SAMPLE_JD_TEXT, SAMPLE_JOB_TITLE } from '../data/examples'

function workflowSteps(job: JobApplication) {
  return [
    { key: 'resume', label: '绑定简历', done: Boolean(job.resume_id) },
    { key: 'optimized', label: 'JD 优化', done: Boolean(job.current_resume_version_id) || job.status === 'optimized' },
    { key: 'interview', label: '面试训练', done: Boolean(job.interview_id) },
    { key: 'report', label: '报告复盘', done: job.status === 'reported' },
  ]
}

function nextAction(job: JobApplication) {
  if (!job.resume_id) return '先绑定一份简历'
  if (!job.current_resume_version_id && job.status !== 'optimized') return '生成 JD 优化版'
  if (!job.interview_id) return '进入岗位面试训练'
  if (job.status !== 'reported') return '完成面试并导出报告'
  return '已完成主链路'
}

function applicationReview(job: JobApplication): ApplicationReview | null {
  const review = job.ats_report?.application_review
  return review && typeof review === 'object' ? review as ApplicationReview : null
}

function reviewTone(review: ApplicationReview | null): 'success' | 'warning' | 'danger' | 'info' | 'neutral' {
  if (!review) return 'neutral'
  if (review.decision === 'apply_now') return 'success'
  if (review.decision === 'revise_before_apply') return 'warning'
  if (review.decision === 'low_priority') return 'info'
  return 'danger'
}

const statusLabels: Record<string, string> = {
  draft: '待处理',
  created: '待处理',
  optimized: '简历已优化',
  interviewing: '面试中',
  reported: '已复盘',
}

export default function JobWorkbenchPage() {
  const navigate = useNavigate()
  const [jobs, setJobs] = useState<JobApplication[]>([])
  const [resumes, setResumes] = useState<ResumeSummary[]>([])
  const [activeTask, setActiveTask] = useState<AsyncTask | null>(null)
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [form, setForm] = useState({ title: '', company: '', jd_text: '', resume_id: '' })

  const loadData = async () => {
    setError('')
    const [jobRes, resumeRes] = await Promise.all([jobsApi.list(), resumeApi.list()])
    setJobs(jobRes.data)
    setResumes(resumeRes.data)
  }

  useEffect(() => {
    loadData().catch((err: any) => setError(err.response?.data?.detail || '岗位工作台加载失败')).finally(() => setLoading(false))
  }, [])

  const createJob = async () => {
    if (!form.title.trim() || !form.jd_text.trim()) return
    setSubmitting(true)
    setError('')
    try {
      await jobsApi.create({
        title: form.title.trim(),
        company: form.company.trim(),
        jd_text: form.jd_text.trim(),
        resume_id: form.resume_id || null,
      })
      setForm({ title: '', company: '', jd_text: '', resume_id: '' })
      await loadData()
    } catch (err: any) {
      setError(err.response?.data?.detail || '创建岗位任务失败')
    } finally {
      setSubmitting(false)
    }
  }

  const fillSampleJob = () => {
    setForm({
      title: SAMPLE_JOB_TITLE,
      company: SAMPLE_COMPANY,
      jd_text: SAMPLE_JD_TEXT,
      resume_id: form.resume_id || resumes[0]?.id || '',
    })
    setError('')
  }

  const runAdapt = async (job: JobApplication) => {
    setError('')
    setActiveTask(null)
    try {
      const taskRes = await jobsApi.adaptResumeTask(job.id)
      let task: AsyncTask = taskRes.data.task
      setActiveTask(task)
      while (!['success', 'failed', 'cancelled'].includes(task.status)) {
        await new Promise((resolve) => window.setTimeout(resolve, 1500))
        const next = await taskApi.get(task.id)
        task = next.data
        setActiveTask(task)
      }
      if (task.status !== 'success') throw new Error(task.error_message || '岗位优化失败')
      await loadData()
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || '岗位优化失败')
    } finally {
      setActiveTask(null)
    }
  }

  const runPreflight = async (job: JobApplication) => {
    setError('')
    try {
      await jobsApi.preflight(job.id)
      await loadData()
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || '投递预审失败')
    }
  }

  if (loading) return <LoadingState label="正在加载岗位工作台" />

  return (
    <AppShell
      title="岗位工作台"
      description="集中推进每个目标岗位的简历、面试和复盘任务。"
      actions={
        <>
          <Button type="button" variant="secondary" onClick={() => navigate('/resumes')}>
            <FileText size={16} />
            简历资产
          </Button>
          <Button type="button" onClick={() => document.getElementById('new-job-form')?.scrollIntoView({ behavior: 'smooth', block: 'start' })}>
            <Plus size={16} />
            新增岗位
          </Button>
        </>
      }
    >
      <div className="space-y-7">
        {error && <div className="rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div>}
        {activeTask && (
          <div className="rounded-lg border border-slate-200 bg-white px-4 py-3 shadow-sm">
            <div className="mb-2 flex items-center justify-between">
              <div className="font-semibold text-slate-950">{activeTask.stage}</div>
              <span className="text-sm font-semibold text-slate-600">{activeTask.progress}%</span>
            </div>
            <ProgressBar value={activeTask.progress} />
          </div>
        )}

        <div className="metric-strip" aria-label="岗位进度概览">
          <div className="metric-strip-item">
            <div className="metric-strip-label">全部岗位</div>
            <div className="metric-strip-value">{jobs.length}</div>
          </div>
          <div className="metric-strip-item">
            <div className="metric-strip-label">本轮待推进</div>
            <div className="metric-strip-value">{jobs.filter((job) => nextAction(job) !== '已完成主链路').length}</div>
          </div>
          <div className="metric-strip-item">
            <div className="metric-strip-label">已进入面试</div>
            <div className="metric-strip-value">{jobs.filter((job) => Boolean(job.interview_id)).length}</div>
          </div>
          <div className="metric-strip-item">
            <div className="metric-strip-label">平均匹配度</div>
            <div className="metric-strip-value">{jobs.length ? `${Math.round(jobs.reduce((sum, job) => sum + Number(job.match_score || 0), 0) / jobs.length)} 分` : '-'}</div>
          </div>
        </div>

        <div className="grid grid-cols-1 items-start gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
          <section className="order-2 min-w-0 xl:order-1">
            <div className="section-heading mb-4">
              <div>
                <h2 className="section-title">岗位推进清单</h2>
                <p className="section-description">按下一步动作排列，打开岗位可查看完整证据和历史版本。</p>
              </div>
              <span className="text-sm text-slate-500">{jobs.length} 个岗位</span>
            </div>
            <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
              {jobs.map((job) => (
                <article key={job.id} className="border-b border-slate-200 p-5 last:border-b-0 hover:bg-slate-50/70" data-testid="job-card">
                  <div className="flex flex-col justify-between gap-5 lg:flex-row lg:items-start">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="text-base font-semibold text-slate-950">{job.title}</h3>
                        <Badge tone={job.status === 'reported' || job.status === 'optimized' ? 'success' : 'neutral'}>{statusLabels[job.status] || job.status}</Badge>
                        <Badge tone={reviewTone(applicationReview(job))}>
                          {applicationReview(job)?.decision_label || '未预审'}
                        </Badge>
                      </div>
                      <div className="mt-1 text-sm text-slate-500">{job.company || '公司待补充'}{job.match_score !== null ? ` · 匹配度 ${job.match_score} 分` : ''}</div>
                      <div className="mt-4 grid grid-cols-4 gap-1" aria-label="岗位流程进度">
                        {workflowSteps(job).map((step) => (
                          <div key={step.key} className="min-w-0">
                            <div className={`h-1 rounded-full ${step.done ? 'bg-emerald-600' : 'bg-slate-200'}`} />
                            <div className={`mt-1.5 truncate text-[11px] font-medium ${step.done ? 'text-slate-700' : 'text-slate-400'}`}>{step.label}</div>
                          </div>
                        ))}
                      </div>
                      <div className="mt-4 flex items-center gap-2 text-sm font-semibold text-slate-800">
                        <CheckCircle2 size={15} className="text-slate-500" />
                        下一步：{nextAction(job)}
                      </div>
                      {applicationReview(job) && (
                        <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">
                          {applicationReview(job)?.summary}
                        </p>
                      )}
                    </div>
                    <div className="flex shrink-0 flex-wrap gap-2 lg:max-w-[210px] lg:justify-end">
                      <Button type="button" size="sm" onClick={() => navigate(`/jobs/${job.id}`)}>
                        打开详情
                        <ArrowRight size={14} />
                      </Button>
                      <Button type="button" size="sm" variant="secondary" onClick={() => runPreflight(job)} disabled={!job.resume_id}>
                        <SearchCheck size={14} />
                        预审
                      </Button>
                      <Button type="button" size="sm" variant="secondary" onClick={() => runAdapt(job)} disabled={!job.resume_id}>
                        <RefreshCcw size={14} />
                        优化
                      </Button>
                      {job.resume_id && (
                        <Button type="button" size="sm" variant="secondary" onClick={() => navigate(`/resumes/${job.resume_id}`)}>
                          <FileText size={14} />
                          简历
                        </Button>
                      )}
                    </div>
                  </div>
                </article>
              ))}
              {jobs.length === 0 && (
                <EmptyState
                  title="还没有岗位记录"
                  description="在右侧录入目标岗位和 JD，后续简历优化、模拟面试和复盘都会归档到这里。"
                  action={<Button type="button" variant="secondary" onClick={fillSampleJob} data-testid="empty-fill-sample-job-button"><ClipboardPaste size={16} />使用示例 JD</Button>}
                />
              )}
            </div>
          </section>

          <aside id="new-job-form" className="workspace-panel order-1 scroll-mt-6 xl:order-2 xl:sticky xl:top-8">
            <div className="workspace-panel-header">
              <h2 className="font-semibold text-slate-950">新增目标岗位</h2>
              <p className="mt-1 text-sm leading-5 text-slate-500">保存 JD 后即可开始匹配和训练。</p>
            </div>
            <div className="workspace-panel-body space-y-4">
              <Field label="岗位名称">
                <input className="input" value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} placeholder="例如：Agent 应用开发" />
              </Field>
              <Field label="公司">
                <input className="input" value={form.company} onChange={(event) => setForm({ ...form, company: event.target.value })} placeholder="公司名称" />
              </Field>
              <Field label="绑定简历">
                <select className="select" value={form.resume_id} onChange={(event) => setForm({ ...form, resume_id: event.target.value })}>
                  <option value="">暂不绑定</option>
                  {resumes.map((resume) => <option key={resume.id} value={resume.id}>{resume.title}</option>)}
                </select>
              </Field>
              <Field label="岗位 JD" hint={`${form.jd_text.length}/40000`}>
                <textarea className="textarea min-h-44" value={form.jd_text} onChange={(event) => setForm({ ...form, jd_text: event.target.value })} maxLength={40000} placeholder="粘贴岗位职责和要求" />
              </Field>
              <div className="grid grid-cols-2 gap-2 border-t border-slate-200 pt-4">
                <Button type="button" variant="secondary" onClick={fillSampleJob} data-testid="fill-sample-job-button">
                  <ClipboardPaste size={16} />
                  示例
                </Button>
                <Button type="button" onClick={createJob} disabled={submitting || !form.title.trim() || !form.jd_text.trim()} data-testid="create-job-button">
                  {submitting ? '创建中...' : '创建岗位'}
                </Button>
              </div>
            </div>
          </aside>
        </div>
      </div>
    </AppShell>
  )
}
