import { useEffect, useMemo, useState } from 'react'
import { useParams, useNavigate } from 'react-router'
import { ArrowLeft, Building2, CheckCircle2, ChevronLeft, ChevronRight, ClipboardCheck, MessageSquarePlus, RefreshCcw, Send } from 'lucide-react'
import AppShell from '../components/AppShell'
import { Badge, Button, Card, EmptyState, LoadingState, ProgressBar } from '../components/ui'
import { interviewApi, type Interview, type InterviewQuestion } from '../services/interview'

const scoreLabels: Record<string, string> = {
  technical_accuracy: '技术准确性',
  project_understanding: '项目理解',
  structure_clarity: '表达结构',
  troubleshooting: '问题定位',
  engineering_delivery: '工程落地',
  reflection: '复盘能力',
  completeness: '完整性',
  logic: '逻辑',
  consistency: '一致性',
  conciseness: '精炼度',
  depth: '深度',
}

const questionTypeLabels: Record<string, string> = {
  technical_detail: '技术细节',
  troubleshooting: '排查定位',
  tradeoff: '方案取舍',
  metrics_reflection: '结果复盘',
  project_deep_dive: '项目追问',
  internship_deep_dive: '实习追问',
  agent_fundamentals: 'Agent 基础',
  system_design: '系统设计',
  behavioral_star: 'STAR 行为题',
  resume_core: '简历要点',
}

const moduleLabels = {
  project: '项目深挖',
  internship: '实习经历',
  agent: 'Agent 八股',
  system_design: '系统设计',
  behavioral: 'HR / 行为面',
  resume: '简历要点',
  other: '其他题目',
} as const

const moduleTones = {
  project: 'info',
  internship: 'success',
  agent: 'warning',
  system_design: 'info',
  behavioral: 'success',
  resume: 'neutral',
  other: 'neutral',
} as const

type QuestionModule = keyof typeof moduleLabels

function getQuestionModule(question: InterviewQuestion): QuestionModule {
  if (question.module === 'project') return 'project'
  if (question.module === 'internship') return 'internship'
  if (question.module === 'agent_fundamentals') return 'agent'
  if (question.module === 'system_design') return 'system_design'
  if (question.module === 'behavioral') return 'behavioral'
  if (question.module === 'resume') return 'resume'
  const pointId = question.resume_point_id || ''
  const title = question.point_title || ''
  if (pointId.startsWith('project:') || title.startsWith('项目：')) return 'project'
  if (pointId.startsWith('internship:') || title.startsWith('实习：')) return 'internship'
  if (pointId.startsWith('agent:') || title.startsWith('Agent 八股：')) return 'agent'
  if (pointId.startsWith('resume:') || title.startsWith('简历：')) return 'resume'
  return 'other'
}

function cleanPointTitle(question: InterviewQuestion) {
  return question.source_section || (question.point_title || '简历要点').replace(/^项目：|^实习：|^Agent 八股：|^简历：/, '')
}

export default function InterviewPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [interview, setInterview] = useState<Interview | null>(null)
  const [questions, setQuestions] = useState<InterviewQuestion[]>([])
  const [currentIndex, setCurrentIndex] = useState(0)
  const [answer, setAnswer] = useState('')
  const [loading, setLoading] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [regenerating, setRegenerating] = useState(false)
  const [submitted, setSubmitted] = useState<InterviewQuestion | null>(null)
  const [initialLoading, setInitialLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!id) return
    loadQuestions()
  }, [id])

  useEffect(() => {
    const current = questions[currentIndex]
    if (!current) return
    setAnswer(current.user_answer || '')
    setSubmitted(current.user_answer ? current : null)
  }, [questions, currentIndex])

  const answeredCount = useMemo(
    () => questions.filter((question) => question.user_answer).length,
    [questions],
  )
  const progress = questions.length ? Math.round((answeredCount / questions.length) * 100) : 0
  const questionGroups = useMemo(() => {
    const orderedModules: QuestionModule[] = ['project', 'internship', 'agent', 'system_design', 'behavioral', 'resume', 'other']
    return orderedModules
      .map((module) => {
        const indexes = questions
          .map((question, index) => ({ question, index }))
          .filter(({ question }) => getQuestionModule(question) === module)
        return {
          module,
          indexes,
          answered: indexes.filter(({ question }) => question.user_answer).length,
        }
      })
      .filter((group) => group.indexes.length > 0)
  }, [questions])

  const loadQuestions = async () => {
    setError('')
    try {
      const [interviewRes, res] = await Promise.all([
        interviewApi.get(id!),
        interviewApi.listQuestions(id!),
      ])
      setInterview(interviewRes.data)
      setQuestions(res.data)
      setCurrentIndex((index) => Math.min(index, Math.max(res.data.length - 1, 0)))
    } catch (err: any) {
      setError(err.response?.data?.detail || '题目加载失败')
    } finally {
      setInitialLoading(false)
    }
  }

  const handleGenerate = async (force = false) => {
    setGenerating(true)
    setError('')
    try {
      await interviewApi.generateQuestions(id!, force)
      await loadQuestions()
    } catch (err: any) {
      setError(err.response?.data?.detail || '生成题目失败')
    } finally {
      setGenerating(false)
    }
  }

  const handleSubmit = async () => {
    if (!answer.trim()) return
    const question = questions[currentIndex]
    setLoading(true)
    setError('')
    try {
      const res = await interviewApi.submitAnswer(id!, question.id, answer.trim())
      setSubmitted(res.data)
      const updated = [...questions]
      updated[currentIndex] = res.data
      setQuestions(updated)
    } catch (err: any) {
      setError(err.response?.data?.detail || '提交失败')
    } finally {
      setLoading(false)
    }
  }

  const handleRegenerate = async () => {
    const question = questions[currentIndex]
    if (!question || question.user_answer) return
    setRegenerating(true)
    setError('')
    try {
      const res = await interviewApi.regenerateQuestion(id!, question.id)
      const updated = [...questions]
      updated[currentIndex] = res.data
      setQuestions(updated)
      setAnswer('')
      setSubmitted(null)
    } catch (err: any) {
      setError(err.response?.data?.detail || '换题失败')
    } finally {
      setRegenerating(false)
    }
  }

  const handleFinish = async () => {
    try {
      await interviewApi.finish(id!)
      navigate(`/reports/${id}`)
    } catch (err: any) {
      setError(err.response?.data?.detail || '生成报告失败')
    }
  }

  if (initialLoading) return <LoadingState label="正在加载面试" />

  if (questions.length === 0) {
    return (
      <AppShell
        title="模拟面试"
        description="基于简历要点和岗位知识库生成分组面试题。"
        actions={
          <Button type="button" variant="secondary" onClick={() => navigate('/resumes')}>
            <ArrowLeft size={16} />
            返回工作台
          </Button>
        }
      >
        <div className="mx-auto max-w-xl">
          {error && <div className="mb-4 rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div>}
          <EmptyState
            title="题库尚未生成"
            description={`点击后会基于 ${interview?.interview_template_name || '综合面'} 轮次和简历可面试要点生成递进式问题。`}
            action={
              <Button type="button" size="lg" onClick={() => handleGenerate()} disabled={generating}>
                <MessageSquarePlus size={16} />
                {generating ? '生成中...' : '生成面试题目'}
              </Button>
            }
          />
        </div>
      </AppShell>
    )
  }

  const current = questions[currentIndex]
  const companyProfile = interview?.company_profile_snapshot || null

  return (
    <AppShell
      title="模拟面试"
      description="逐题作答后即时获得评分、评语和可背诵版答案。完成 3 题即可生成报告。"
      actions={
        <>
          <Button type="button" variant="secondary" onClick={() => navigate('/resumes')}>
            <ArrowLeft size={16} />
            返回
          </Button>
                  <Button type="button" variant="success" onClick={handleFinish} disabled={answeredCount < 3} data-testid="finish-interview-button">
            <ClipboardCheck size={16} />
            生成报告
          </Button>
          <Button type="button" variant="secondary" onClick={() => handleGenerate(true)} disabled={generating || answeredCount > 0}>
            <RefreshCcw size={16} />
            {generating ? '生成中...' : '重建题库'}
          </Button>
        </>
      }
    >
      <div className="space-y-6">
        {error && <div className="rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div>}

        <Card data-testid="interview-progress-card">
          <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-center">
            <div>
              <div className="flex items-center gap-2">
                <Badge tone="info">第 {currentIndex + 1} / {questions.length} 题</Badge>
                <Badge tone={answeredCount >= 3 ? 'success' : 'warning'}>已完成 {answeredCount} 题</Badge>
                <Badge tone="neutral">{interview?.interview_template_name || '综合面'}</Badge>
              </div>
              <p className="mt-3 text-sm text-slate-500">
                当前进度 {progress}%
                {interview?.template_config_snapshot?.question_focus?.length
                  ? ` · 本轮重点：${interview.template_config_snapshot.question_focus.slice(0, 4).join(' / ')}`
                  : ''}
              </p>
            </div>
            <div className="min-w-64 flex-1 lg:max-w-md">
              <ProgressBar value={progress} />
            </div>
          </div>
        </Card>

        {companyProfile?.matched_company && (
          <div className="border-y border-slate-200 bg-slate-50 px-4 py-4">
            <div className="flex flex-col justify-between gap-3 lg:flex-row lg:items-center">
              <div className="flex min-w-0 items-start gap-3">
                <Building2 size={18} className="mt-0.5 shrink-0 text-slate-600" />
                <div className="min-w-0">
                  <div className="font-semibold text-slate-950">本轮参考：{companyProfile.matched_company} · {companyProfile.matched_position}</div>
                  <div className="mt-1 text-sm text-slate-600">
                    {companyProfile.source_count} 份面经 · {companyProfile.profile_confidence === 'low' ? '样本较少' : companyProfile.profile_confidence === 'high' ? '样本充分' : '样本一般'}
                  </div>
                </div>
              </div>
              <div className="flex flex-wrap gap-2 lg:justify-end">
                {(companyProfile.matched_topics || []).slice(0, 5).map((item: any) => <Badge key={item.topic_key || item.name}>{item.name}</Badge>)}
              </div>
            </div>
          </div>
        )}

        <div className="grid grid-cols-1 gap-6 xl:grid-cols-[320px_minmax(0,1fr)]">
          <Card className="xl:sticky xl:top-7 xl:self-start" data-testid="question-navigation">
            <div className="mb-4">
              <h2 className="card-title">题目导航</h2>
              <p className="card-subtitle">按顺序作答，也可回看已评分题。</p>
            </div>
            <div className="max-h-[540px] space-y-4 overflow-auto pr-1">
              {questionGroups.map((group) => (
                <div key={group.module} className="space-y-2">
                  <div className="flex items-center justify-between gap-3">
                    <Badge tone={moduleTones[group.module]}>{moduleLabels[group.module]}</Badge>
                    <span className="text-xs text-slate-500">
                      {group.answered}/{group.indexes.length}
                    </span>
                  </div>
                  <div className="grid gap-2">
                    {group.indexes.map(({ question, index }) => (
                      <button
                        key={question.id}
                        type="button"
                        onClick={() => setCurrentIndex(index)}
                        className={`rounded-md border px-3 py-2 text-left text-sm transition ${
                          index === currentIndex
                            ? 'border-slate-700 bg-slate-50 text-slate-950'
                            : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50'
                        }`}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-semibold">Q{index + 1}</span>
                          {question.user_answer && <CheckCircle2 size={15} className="text-emerald-600" />}
                        </div>
                        <div className="mt-1 text-xs text-slate-500">{cleanPointTitle(question)}</div>
                        <div className="mt-1 line-clamp-2 leading-5">{question.question}</div>
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </Card>

          <div className="space-y-6">
            <Card>
              <div className="mb-3 flex items-center justify-between gap-3">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone={moduleTones[getQuestionModule(current)]}>{moduleLabels[getQuestionModule(current)]}</Badge>
                  <Badge tone="neutral">{cleanPointTitle(current)}</Badge>
                </div>
                {current.total_score !== null && <Badge tone="success">{current.total_score} 分</Badge>}
              </div>
              <h2 className="text-xl font-bold leading-8 text-slate-950">{current.question}</h2>
              <div className="mt-4 grid gap-3 lg:grid-cols-3">
                <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
                  <div className="text-xs text-slate-500">题型</div>
                  <div className="mt-1 text-sm font-semibold text-slate-900">
                    {questionTypeLabels[current.question_type] || '追问'}
                  </div>
                </div>
                <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
                  <div className="text-xs text-slate-500">难度</div>
                  <div className="mt-1 text-sm font-semibold text-slate-900">
                    {current.question_quality?.difficulty || '中'}
                  </div>
                </div>
                <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
                  <div className="text-xs text-slate-500">考察点</div>
                  <div className="mt-1 text-sm font-semibold text-slate-900">
                    {current.question_quality?.reason || '基于简历经历追问'}
                  </div>
                </div>
              </div>
              {Boolean(current.evidence?.length) && (
                <div className="mt-4 rounded-md border border-slate-200 border-l-4 bg-slate-50 p-4" data-testid="question-evidence-panel" style={{ borderLeftColor: '#436052' }}>
                  <div className="text-sm font-semibold text-slate-950">来源依据</div>
                  <div className="mt-2 space-y-2">
                    {current.evidence?.slice(0, 2).map((item, index) => (
                      <div key={`${item.source_title}-${index}`} className="text-sm leading-6 text-slate-700">
                        <span className="font-semibold">{item.source_section} / {item.source_title}：</span>
                        {item.source_snippet}
                      </div>
                    ))}
                  </div>
                </div>
              )}
              <textarea
                placeholder="请输入你的回答..."
                value={answer}
                onChange={(event) => setAnswer(event.target.value)}
                className="textarea mt-5 min-h-48"
                maxLength={8000}
                data-testid="answer-textarea"
              />
              <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
                <div className="text-xs text-slate-500">{answer.length}/8000 字符</div>
                <div className="flex flex-wrap gap-2">
                  <Button
                    type="button"
                    variant="secondary"
                    disabled={currentIndex === 0}
                    onClick={() => setCurrentIndex((index) => Math.max(0, index - 1))}
                  >
                    <ChevronLeft size={16} />
                    上一题
                  </Button>
                  <Button type="button" onClick={handleSubmit} disabled={loading || !answer.trim()} data-testid="submit-answer-button">
                    <Send size={16} />
                    {loading ? '评分中...' : current.user_answer ? '重新评分' : '提交回答'}
                  </Button>
                  <Button
                    type="button"
                    variant="secondary"
                    onClick={handleRegenerate}
                    disabled={regenerating || Boolean(current.user_answer)}
                  >
                    <RefreshCcw size={16} />
                    {regenerating ? '换题中...' : '换一种问法'}
                  </Button>
                  <Button
                    type="button"
                    variant="secondary"
                    disabled={currentIndex >= questions.length - 1}
                    onClick={() => setCurrentIndex((index) => Math.min(questions.length - 1, index + 1))}
                    data-testid="next-question-button"
                  >
                    下一题
                    <ChevronRight size={16} />
                  </Button>
                </div>
              </div>
            </Card>

            {submitted && (
              <Card>
                <div className="mb-5 flex items-start justify-between gap-4">
                  <div>
                    <h3 className="card-title">评分与参考答案</h3>
                    <p className="card-subtitle">评分会结合简历上下文、岗位知识和回答结构。</p>
                  </div>
                  <div className="text-right">
                    <div className="text-3xl font-bold text-slate-900">{submitted.total_score}</div>
                    <div className="text-xs text-slate-500">总分</div>
                  </div>
                </div>

                {submitted.scores && (
                  <div className="score-grid mb-5">
                    {Object.entries(submitted.scores).map(([key, score]) => (
                      <div key={key} className="rounded-lg border border-slate-200 bg-slate-50 p-3">
                        <div className="text-xs text-slate-500">{scoreLabels[key] || key}</div>
                        <div className="mt-1 text-xl font-bold text-slate-950">{String(score)}</div>
                      </div>
                    ))}
                  </div>
                )}

                {submitted.score_details && (
                  <div className="mb-5 grid gap-3 lg:grid-cols-2" data-testid="score-details-panel">
                    {Object.entries(submitted.score_details).map(([key, detail]: [string, any]) => (
                      <div key={key} className="rounded-lg border border-slate-200 bg-white p-4">
                        <div className="flex items-center justify-between gap-3">
                          <h4 className="font-semibold text-slate-950">{scoreLabels[key] || detail.label || key}</h4>
                          <Badge tone={detail.risk === '高' ? 'danger' : detail.risk === '中' ? 'warning' : 'success'}>
                            风险 {detail.risk || '低'}
                          </Badge>
                        </div>
                        {detail.issue && <p className="mt-2 text-sm leading-6 text-slate-600">扣分点：{detail.issue}</p>}
                        {detail.suggestion && <p className="mt-2 text-sm leading-6 text-slate-700">建议：{detail.suggestion}</p>}
                      </div>
                    ))}
                  </div>
                )}

                <div className="grid gap-4 lg:grid-cols-2">
                  <div className="rounded-lg border border-slate-200 bg-white p-4">
                    <h4 className="font-semibold text-slate-950">评语</h4>
                    <p className="mt-2 text-sm leading-6 text-slate-600">{submitted.feedback}</p>
                  </div>
                  <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-4">
                    <h4 className="font-semibold text-emerald-900">精简答案</h4>
                    <p className="mt-2 text-sm leading-6 text-emerald-800">{submitted.refined_answer}</p>
                  </div>
                </div>
              </Card>
            )}
          </div>
        </div>
      </div>
    </AppShell>
  )
}
