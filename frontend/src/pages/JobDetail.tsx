import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router'
import { ArrowLeft, BrainCircuit, Download, FileText, Gauge, Play, RefreshCcw, RotateCcw, ShieldCheck, Target, XCircle } from 'lucide-react'
import AppShell from '../components/AppShell'
import { Badge, Button, Card, EmptyState, LoadingState, ProgressBar, StatTile } from '../components/ui'
import { interviewApi } from '../services/interview'
import { jobsApi, type JobApplication } from '../services/jobs'
import { type AtsReport } from '../services/resume'
import { taskApi, type AsyncTask } from '../services/tasks'

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

function AtsPanel({ report }: { report: AtsReport | null }) {
  if (!report) {
    return <EmptyState title="暂无 ATS 评分" description="先执行岗位简历优化，系统会生成逐维度匹配分析。" />
  }
  return (
    <div className="space-y-4" data-testid="ats-panel">
      <div className="flex flex-col justify-between gap-3 rounded-lg border border-cyan-100 bg-cyan-50 p-4 lg:flex-row lg:items-center">
        <div>
          <h2 className="card-title">ATS/JD 匹配评分</h2>
          <p className="card-subtitle">按硬技能、软技能、项目证据、关键词覆盖、教育经验和格式风险解释分数。</p>
        </div>
        <div className="flex items-center gap-2">
          <Gauge size={20} className="text-cyan-700" />
          <span className="text-3xl font-bold text-slate-950">{report.total_score}</span>
          <span className="text-sm text-slate-500">/100</span>
        </div>
      </div>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {(report.dimensions || []).map((dimension) => (
          <div key={dimension.key} className="rounded-lg border border-slate-200 bg-white p-4">
            <div className="mb-2 flex items-center justify-between gap-2">
              <div className="font-semibold text-slate-950">{dimension.name}</div>
              <Badge tone={scoreTone(Number(dimension.score || 0))}>{dimension.score}</Badge>
            </div>
            <ProgressBar value={Number(dimension.score || 0)} />
            {dimension.covered?.length ? (
              <div className="mt-3 text-xs leading-5 text-emerald-700">已覆盖：{dimension.covered.slice(0, 5).join('、')}</div>
            ) : null}
            {dimension.missing?.length ? (
              <div className="mt-2 text-xs leading-5 text-rose-700">缺口：{dimension.missing.slice(0, 5).join('、')}</div>
            ) : null}
            {dimension.risk?.length ? (
              <div className="mt-2 text-xs leading-5 text-amber-700">风险：{dimension.risk.slice(0, 3).join('；')}</div>
            ) : null}
            {dimension.suggestion && <div className="mt-2 text-xs leading-5 text-slate-500">{dimension.suggestion}</div>}
          </div>
        ))}
      </div>
    </div>
  )
}

export default function JobDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [job, setJob] = useState<JobApplication | null>(null)
  const [activeTask, setActiveTask] = useState<AsyncTask | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  const atsReport = useMemo(() => {
    const report = job?.ats_report
    return report && Array.isArray((report as AtsReport).dimensions) ? report as AtsReport : null
  }, [job])

  const loadJob = async () => {
    if (!id) return
    setError('')
    const res = await jobsApi.get(id)
    setJob(res.data)
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
      const res = await jobsApi.exportDeliveryResume(job.id)
      downloadBlob(res.data, `${job.company ? `${job.company}-` : ''}${job.title}-投递版简历.docx`)
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
        // 面试页可继续手动生成或重建题库。
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
      description="一个 JD 对应一个求职任务、一个简历版本、一组面试训练和一份报告。"
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
          <Button type="button" onClick={runAdapt} disabled={busy || !job.resume_id}>
            <RefreshCcw size={16} />
            {busy ? '处理中...' : '优化简历'}
          </Button>
        </>
      }
    >
      <div className="space-y-6">
        {error && <div className="rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div>}
        {message && <div className="rounded-md border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{message}</div>}

        {activeTask && (
          <Card data-testid="job-task-progress">
            <div className="mb-3 flex flex-col justify-between gap-3 lg:flex-row lg:items-center">
              <div>
                <div className="font-semibold text-slate-950">{activeTask.stage}</div>
                <div className="mt-1 text-xs text-slate-500">
                  {activeTask.queue_backend} · {activeTask.queue_name}
                  {activeTask.external_job_id ? ` · job ${activeTask.external_job_id.slice(0, 8)}` : ''}
                </div>
              </div>
              <div className="flex items-center gap-2">
                <Badge tone={activeTask.status === 'failed' ? 'danger' : activeTask.status === 'success' ? 'success' : 'info'}>
                  {activeTask.status}
                </Badge>
                <Badge tone="neutral">{activeTask.progress}%</Badge>
              </div>
            </div>
            <ProgressBar value={activeTask.progress} />
            <div className="mt-3 flex flex-wrap gap-2">
              {activeTask.status === 'failed' && activeTask.retry_count < activeTask.max_retries && (
                <Button type="button" size="sm" variant="secondary" onClick={retryTask}>
                  <RotateCcw size={14} />
                  重试
                </Button>
              )}
              {!['success', 'failed', 'cancelled'].includes(activeTask.status) && (
                <Button type="button" size="sm" variant="danger" onClick={cancelTask}>
                  <XCircle size={14} />
                  取消
                </Button>
              )}
            </div>
          </Card>
        )}

        <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
          <StatTile label="任务状态" value={job.status} meta="岗位工作流阶段" icon={<Target size={18} />} />
          <StatTile label="匹配评分" value={job.match_score ?? '-'} meta="ATS/JD 总分" icon={<Gauge size={18} />} />
          <StatTile label="简历版本" value={job.current_resume_version_id ? '已生成' : '未生成'} meta="当前投递版本" icon={<FileText size={18} />} />
          <StatTile label="面试训练" value={job.interview_id ? '已创建' : '未开始'} meta="关联 JD 出题" icon={<BrainCircuit size={18} />} />
        </div>

        <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]">
          <Card>
            <div className="mb-5 flex items-start justify-between gap-4">
              <div>
                <h2 className="card-title">岗位 JD</h2>
                <p className="card-subtitle">用于匹配评分、简历优化和面试题生成。</p>
              </div>
              <Badge tone={job.resume_id ? 'success' : 'warning'}>{job.resume_id ? '已绑定简历' : '未绑定简历'}</Badge>
            </div>
            <div className="max-h-[520px] overflow-auto whitespace-pre-wrap rounded-lg border border-slate-200 bg-slate-50 p-4 text-sm leading-7 text-slate-700">
              {job.jd_text}
            </div>
          </Card>

          <Card>
            <div className="mb-5 flex items-start justify-between gap-4">
              <div>
                <h2 className="card-title">投递闭环</h2>
                <p className="card-subtitle">先生成 JD 优化版，再导出投递版或进入面试训练。</p>
              </div>
              <ShieldCheck size={20} className="text-emerald-700" />
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <Button type="button" onClick={runAdapt} disabled={busy || !job.resume_id} data-testid="job-adapt-button">
                <RefreshCcw size={16} />
                生成 JD 优化版
              </Button>
              <Button type="button" variant="secondary" onClick={exportResume} disabled={busy || !job.current_resume_version_id} data-testid="export-delivery-resume-button">
                <Download size={16} />
                导出投递版 Word
              </Button>
              <Button type="button" variant="success" onClick={startInterview} disabled={busy || !job.resume_id} data-testid="start-job-interview-button">
                <Play size={16} />
                {job.interview_id ? '继续面试训练' : '生成岗位面试'}
              </Button>
              {job.interview_id && (
                <Button type="button" variant="secondary" onClick={() => navigate(`/reports/${job.interview_id}`)}>
                  <FileText size={16} />
                  查看面试报告
                </Button>
              )}
            </div>
          </Card>
        </div>

        <Card>
          <AtsPanel report={atsReport} />
        </Card>
      </div>
    </AppShell>
  )
}
