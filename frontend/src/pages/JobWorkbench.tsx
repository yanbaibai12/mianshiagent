import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router'
import { ArrowRight, BriefcaseBusiness, CheckCircle2, FileText, RefreshCcw, Sparkles, Target } from 'lucide-react'
import AppShell from '../components/AppShell'
import { Badge, Button, Card, EmptyState, Field, LoadingState, ProgressBar, StatTile } from '../components/ui'
import { jobsApi, type JobApplication } from '../services/jobs'
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

  if (loading) return <LoadingState label="正在加载岗位工作台" />

  return (
    <AppShell
      title="岗位工作台"
      description="一个 JD 对应一个求职任务、一个简历版本、一组面试训练和一份报告。"
      actions={
        <Button type="button" variant="secondary" onClick={() => navigate('/resumes')}>
          返回简历
        </Button>
      }
    >
      <div className="space-y-6">
        {error && <div className="rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div>}
        {activeTask && (
          <Card>
            <div className="mb-2 flex items-center justify-between">
              <div className="font-semibold text-slate-950">{activeTask.stage}</div>
              <Badge tone="info">{activeTask.progress}%</Badge>
            </div>
            <ProgressBar value={activeTask.progress} />
          </Card>
        )}

        {jobs.length === 0 && (
          <Card className="border-cyan-100 bg-cyan-50">
            <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-center">
              <div>
                <h2 className="card-title">从一条免费版主链路开始</h2>
                <p className="card-subtitle">
                  上传或选择一份简历，填入 JD，生成优化版简历，再进入岗位面试和报告导出。
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button type="button" variant="secondary" onClick={() => navigate('/resumes')}>
                  <FileText size={16} />
                  上传简历
                </Button>
                <Button type="button" onClick={fillSampleJob} data-testid="empty-fill-sample-job-button">
                  <Sparkles size={16} />
                  填入示例 JD
                </Button>
              </div>
            </div>
          </Card>
        )}

        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
          <StatTile label="岗位任务" value={jobs.length} meta="JD 工作流数量" icon={<BriefcaseBusiness size={18} />} />
          <StatTile label="已优化" value={jobs.filter((job) => job.status === 'optimized').length} meta="已生成简历版本" icon={<Sparkles size={18} />} />
          <StatTile label="待推进" value={jobs.filter((job) => nextAction(job) !== '已完成主链路').length} meta="还有下一步动作" icon={<CheckCircle2 size={18} />} />
          <StatTile label="平均匹配" value={jobs.length ? Math.round(jobs.reduce((sum, job) => sum + Number(job.match_score || 0), 0) / jobs.length) : '-'} meta="ATS/JD 分数" icon={<Target size={18} />} />
        </div>

        <div className="grid grid-cols-1 gap-6 xl:grid-cols-[380px_minmax(0,1fr)]">
          <Card>
            <div className="mb-5">
              <h2 className="card-title">创建岗位任务</h2>
              <p className="card-subtitle">先绑定一份简历，后续可直接生成 JD 优化版。</p>
            </div>
            <div className="space-y-4">
              <Field label="岗位名称">
                <input className="input" value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} />
              </Field>
              <Field label="公司">
                <input className="input" value={form.company} onChange={(event) => setForm({ ...form, company: event.target.value })} />
              </Field>
              <Field label="绑定简历">
                <select className="select" value={form.resume_id} onChange={(event) => setForm({ ...form, resume_id: event.target.value })}>
                  <option value="">暂不绑定</option>
                  {resumes.map((resume) => <option key={resume.id} value={resume.id}>{resume.title}</option>)}
                </select>
              </Field>
              <Field label="岗位 JD" hint={`${form.jd_text.length}/40000 字符`}>
                <textarea className="textarea min-h-52" value={form.jd_text} onChange={(event) => setForm({ ...form, jd_text: event.target.value })} maxLength={40000} />
              </Field>
              <Button type="button" variant="secondary" className="w-full" onClick={fillSampleJob} data-testid="fill-sample-job-button">
                <Sparkles size={16} />
                填入示例 JD
              </Button>
              <Button type="button" className="w-full" onClick={createJob} disabled={submitting || !form.title.trim() || !form.jd_text.trim()} data-testid="create-job-button">
                {submitting ? '创建中...' : '创建岗位任务'}
              </Button>
            </div>
          </Card>

          <Card>
            <div className="mb-5">
              <h2 className="card-title">岗位列表</h2>
              <p className="card-subtitle">每个岗位任务都可以独立优化、进入面试和复盘。</p>
            </div>
            <div className="space-y-3">
              {jobs.map((job) => (
                <div key={job.id} className="rounded-lg border border-slate-200 bg-slate-50 p-4" data-testid="job-card">
                  <div className="flex flex-col justify-between gap-3 lg:flex-row lg:items-start">
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="font-semibold text-slate-950">{job.company ? `${job.company} · ` : ''}{job.title}</h3>
                        <Badge tone={job.status === 'optimized' ? 'success' : 'neutral'}>{job.status}</Badge>
                        {job.match_score !== null && <Badge tone="info">{job.match_score} 分</Badge>}
                      </div>
                      <div className="mt-3 flex flex-wrap gap-2">
                        {workflowSteps(job).map((step) => (
                          <span
                            key={step.key}
                            className={`inline-flex items-center gap-1 rounded-md border px-2.5 py-1 text-xs font-semibold ${
                              step.done
                                ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                                : 'border-slate-200 bg-white text-slate-500'
                            }`}
                          >
                            {step.done && <CheckCircle2 size={12} />}
                            {step.label}
                          </span>
                        ))}
                      </div>
                      <div className="mt-3 text-sm font-semibold text-cyan-800">下一步：{nextAction(job)}</div>
                      <p className="mt-2 max-h-12 overflow-hidden text-sm leading-6 text-slate-500">{job.jd_text}</p>
                    </div>
                    <div className="flex shrink-0 flex-wrap gap-2">
                      <Button type="button" size="sm" onClick={() => runAdapt(job)} disabled={!job.resume_id}>
                        <RefreshCcw size={14} />
                        优化简历
                      </Button>
                      <Button type="button" size="sm" variant="secondary" onClick={() => navigate(`/jobs/${job.id}`)}>
                        <ArrowRight size={14} />
                        打开详情
                      </Button>
                      {job.resume_id && (
                        <Button type="button" size="sm" variant="secondary" onClick={() => navigate(`/resumes/${job.resume_id}`)}>
                          <FileText size={14} />
                          简历版本
                        </Button>
                      )}
                    </div>
                  </div>
                </div>
              ))}
              {jobs.length === 0 && <EmptyState title="暂无岗位任务" description="创建第一个 JD 后，这里会形成独立求职任务。" />}
            </div>
          </Card>
        </div>
      </div>
    </AppShell>
  )
}
