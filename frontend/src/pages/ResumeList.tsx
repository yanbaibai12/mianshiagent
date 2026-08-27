import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router'
import {
  ClipboardPaste,
  FileText,
  Gauge,
  MessageSquareText,
  PlusCircle,
  SearchCheck,
  Route,
  Target,
  Trash2,
  UploadCloud,
} from 'lucide-react'
import AppShell from '../components/AppShell'
import { Badge, Button, Card, EmptyState, Field, LoadingState, StatTile } from '../components/ui'
import { resumeApi, ResumeSummary } from '../services/resume'
import { interviewApi, Interview } from '../services/interview'
import { SAMPLE_RESUME_TEXT, SAMPLE_RESUME_TITLE } from '../data/examples'

function formatDate(value: string) {
  return new Date(value).toLocaleString()
}

export default function ResumeListPage() {
  const [resumes, setResumes] = useState<ResumeSummary[]>([])
  const [interviews, setInterviews] = useState<Interview[]>([])
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [title, setTitle] = useState('')
  const [text, setText] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [error, setError] = useState('')
  const navigate = useNavigate()

  useEffect(() => {
    loadData()
  }, [])

  const completedInterviews = useMemo(
    () => interviews.filter((interview) => interview.status === 'completed').length,
    [interviews],
  )

  const averageScore = useMemo(() => {
    const scored = interviews.filter((interview) => typeof interview.total_score === 'number')
    if (scored.length === 0) return '-'
    const total = scored.reduce((sum, interview) => sum + Number(interview.total_score), 0)
    return Math.round(total / scored.length)
  }, [interviews])

  const loadData = async () => {
    setLoading(true)
    setError('')
    try {
      const [resumeRes, interviewRes] = await Promise.all([
        resumeApi.list(),
        interviewApi.list(),
      ])
      setResumes(resumeRes.data)
      setInterviews(interviewRes.data)
    } catch (err: any) {
      setError(err.response?.data?.detail || '数据加载失败')
    } finally {
      setLoading(false)
    }
  }

  const handleUpload = async (event: React.FormEvent) => {
    event.preventDefault()
    setError('')
    if (!title.trim()) {
      setError('请填写简历名称')
      return
    }
    if (!file && !text.trim()) {
      setError('请上传文件或粘贴简历文本')
      return
    }

    setUploading(true)
    try {
      if (!file) {
        const res = await resumeApi.upload({ title: title.trim(), text })
        navigate(`/resumes/${res.data.id}`)
        return
      }
      const formData = new FormData()
      formData.append('title', title.trim())
      formData.append('file', file)
      const res = await resumeApi.upload(formData)
      navigate(`/resumes/${res.data.id}`)
    } catch (err: any) {
      setError(err.response?.data?.detail || '上传失败')
    } finally {
      setUploading(false)
    }
  }

  const fillSampleResume = () => {
    setTitle(SAMPLE_RESUME_TITLE)
    setText(SAMPLE_RESUME_TEXT)
    setFile(null)
    setError('')
  }

  const handleDeleteInterview = async (interviewId: string) => {
    const confirmed = window.confirm('确认删除这条面试记录？删除后无法恢复。')
    if (!confirmed) return
    setError('')
    try {
      await interviewApi.delete(interviewId)
      await loadData()
    } catch (err: any) {
      setError(err.response?.data?.detail || '删除面试失败')
    }
  }

  if (loading) return <LoadingState label="正在加载工作台" />

  return (
    <AppShell
      title="求职训练工作台"
      description="集中管理简历版本、面试记录和复盘结果。"
      actions={
        <Button type="button" onClick={() => navigate('/interviews/new')}>
          <PlusCircle size={16} />
          创建面试
        </Button>
      }
    >
      <div className="space-y-6">
        {error && (
          <div className="rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
            {error}
          </div>
        )}
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4 lg:gap-4">
          <StatTile label="简历资产" value={resumes.length} meta="已保存简历版本" icon={<FileText size={18} />} />
          <StatTile label="面试记录" value={interviews.length} meta={`${completedInterviews} 次已完成`} icon={<MessageSquareText size={18} />} />
          <StatTile label="平均得分" value={averageScore} meta="基于已完成报告" icon={<Gauge size={18} />} />
          <StatTile
            label="下一步"
            value={resumes.length === 0 ? '上传简历' : interviews.length === 0 ? '创建面试' : '复盘报告'}
            meta="围绕主链路继续推进"
            icon={<Target size={18} />}
          />
        </div>

        <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1.25fr)_minmax(360px,0.75fr)]">
          <Card>
            <div className="mb-5 flex items-start justify-between gap-4">
              <div>
                <h2 className="card-title">上传简历</h2>
                <p className="card-subtitle">支持 PDF/DOCX；当前 MVP 推荐粘贴文本，解析结果可在详情页继续编辑。</p>
              </div>
              <Badge tone="info">结构化解析</Badge>
            </div>

            <form onSubmit={handleUpload} className="space-y-4" data-testid="resume-upload-form">
              <Field label="简历名称">
                <input
                  type="text"
                  placeholder="例如：后端开发-校招版"
                  value={title}
                  onChange={(event) => setTitle(event.target.value)}
                  className="input"
                  maxLength={200}
                  required
                />
              </Field>

              <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                <Field label="上传文件" hint="文件大小上限由后端配置控制">
                  <input
                    type="file"
                    accept=".pdf,.docx"
                    onChange={(event) => setFile(event.target.files?.[0] || null)}
                    className="file-input"
                  />
                </Field>
                <Field label="粘贴文本" hint={`${text.length}/80000 字符`}>
                  <textarea
                    placeholder="粘贴 Markdown 或纯文本简历"
                    value={text}
                    onChange={(event) => setText(event.target.value)}
                    className="textarea min-h-36"
                    maxLength={80000}
                  />
                </Field>
              </div>

            <div className="flex flex-wrap items-center gap-3">
                <Button type="submit" disabled={uploading} data-testid="upload-resume-button">
                  <UploadCloud size={16} />
                  {uploading ? '解析中...' : '上传并解析'}
                </Button>
                <Button type="button" variant="secondary" onClick={fillSampleResume} data-testid="fill-sample-resume-button">
                  <ClipboardPaste size={16} />
                  填入示例简历
                </Button>
                <Button type="button" variant="secondary" onClick={loadData}>
                  <SearchCheck size={16} />
                  刷新数据
                </Button>
              </div>
            </form>
          </Card>

          <div className="space-y-6">
            <Card>
              <div className="mb-5 flex items-start justify-between gap-4">
                <div>
                  <h2 className="card-title">下一步行动</h2>
                  <p className="card-subtitle">围绕一条可复盘链路推进：简历、JD、面试、报告。</p>
                </div>
                <Route size={18} className="text-slate-600" />
              </div>

              <div className="space-y-3">
                {resumes.length === 0 && (
                  <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
                    <div className="font-semibold text-slate-950">先上传一份简历</div>
                    <p className="mt-1 text-sm leading-6 text-slate-600">上传后可以检查项目、技能和面试要点。</p>
                  </div>
                )}
                {resumes.length > 0 && interviews.length === 0 && (
                  <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
                    <div className="font-semibold text-slate-950">创建第一场模拟面试</div>
                    <p className="mt-1 text-sm leading-6 text-slate-600">至少完成 3 道题后，就可以生成复盘报告。</p>
                    <Button type="button" className="mt-3" onClick={() => navigate('/interviews/new')}>
                      <PlusCircle size={16} />
                      创建面试
                    </Button>
                  </div>
                )}
                {interviews.length > 0 && completedInterviews === 0 && (
                  <div className="rounded-lg border border-amber-100 bg-amber-50 p-4">
                    <div className="font-semibold text-amber-950">继续完成进行中的面试</div>
                    <p className="mt-1 text-sm leading-6 text-amber-800">完成作答后，报告会给出薄弱点和复习建议。</p>
                  </div>
                )}
                {completedInterviews > 0 && (
                  <div className="rounded-lg border border-emerald-100 bg-emerald-50 p-4">
                    <div className="font-semibold text-emerald-950">复盘并针对薄弱点重练</div>
                    <p className="mt-1 text-sm leading-6 text-emerald-800">优先补齐项目背景、个人贡献、结果指标和方案取舍。</p>
                  </div>
                )}
              </div>
            </Card>
          </div>
        </div>

        <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)]">
          <Card>
            <div className="mb-5 flex items-center justify-between gap-4">
              <div>
                <h2 className="card-title">历史面试</h2>
                <p className="card-subtitle">继续作答或查看已生成报告。</p>
              </div>
              <Button type="button" variant="secondary" size="sm" onClick={() => navigate('/interviews/new')}>
                <PlusCircle size={14} />
                新建
              </Button>
            </div>
            <div className="space-y-3">
              {interviews.map((interview) => (
                <div
                  key={interview.id}
                  className="rounded-lg border border-slate-200 bg-white p-4 transition hover:border-slate-400 hover:bg-slate-50"
                >
                  <div className="flex items-start justify-between gap-3">
                    <button
                      type="button"
                      onClick={() => navigate(interview.status === 'completed' ? `/reports/${interview.id}` : `/interviews/${interview.id}`)}
                      className="min-w-0 flex-1 text-left"
                    >
                      <div className="font-semibold text-slate-950">
                        {interview.status === 'completed' ? '已完成面试' : '进行中面试'}
                      </div>
                      <div className="mt-2 text-sm text-slate-500">
                        {formatDate(interview.created_at)}
                        {interview.total_score !== null ? ` · 总分 ${interview.total_score}` : ''}
                      </div>
                    </button>
                    <div className="flex shrink-0 items-center gap-2">
                      <Badge tone={interview.status === 'completed' ? 'success' : 'warning'}>
                        {interview.status === 'completed' ? '报告' : '继续'}
                      </Badge>
                      <Button type="button" variant="ghost" size="sm" onClick={() => handleDeleteInterview(interview.id)}>
                        <Trash2 size={14} />
                      </Button>
                    </div>
                  </div>
                </div>
              ))}
              {interviews.length === 0 && (
                <EmptyState
                  title="暂无面试记录"
                  description="上传简历后即可创建第一场模拟面试。"
                  action={
                    <Button type="button" variant="secondary" onClick={() => navigate('/interviews/new')}>
                      <PlusCircle size={16} />
                      创建面试
                    </Button>
                  }
                />
              )}
            </div>
          </Card>

          <Card>
            <div className="mb-5 flex items-center justify-between gap-4">
              <div>
                <h2 className="card-title">我的简历</h2>
                <p className="card-subtitle">进入详情后可优化、JD 适配、编辑结构化结果。</p>
              </div>
              <Badge tone="neutral">{resumes.length} 份</Badge>
            </div>

            <div className="grid gap-3">
              {resumes.map((resume) => (
                <button
                  key={resume.id}
                  type="button"
                  onClick={() => navigate(`/resumes/${resume.id}`)}
                  className="rounded-lg border border-slate-200 bg-white p-4 text-left transition hover:border-slate-400 hover:bg-slate-50"
                >
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <h3 className="font-semibold text-slate-950">{resume.title}</h3>
                      <p className="mt-1 text-sm text-slate-500">更新于 {formatDate(resume.updated_at)}</p>
                    </div>
                    <div className="flex items-center gap-2">
                      {resume.template_id ? <Badge tone="info">{resume.template_id}</Badge> : <Badge>未优化</Badge>}
                      {resume.match_score ? <Badge tone="success">{resume.match_score} 匹配</Badge> : null}
                    </div>
                  </div>
                </button>
              ))}
              {resumes.length === 0 && (
                <EmptyState title="还没有简历" description="上传一份简历后，系统会自动解析并生成可面试要点。" />
              )}
            </div>
          </Card>
        </div>
      </div>
    </AppShell>
  )
}
