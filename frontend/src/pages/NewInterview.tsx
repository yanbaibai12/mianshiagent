import { useEffect, useState } from 'react'
import { useSearchParams, useNavigate } from 'react-router'
import { ArrowLeft, BriefcaseBusiness, MessageSquareText, Play } from 'lucide-react'
import AppShell from '../components/AppShell'
import { Badge, Button, Card, EmptyState, Field, LoadingState } from '../components/ui'
import { interviewApi } from '../services/interview'
import { resumeApi, ResumeSummary } from '../services/resume'
import { businessApi, BusinessEntitlements } from '../services/business'
import { SAMPLE_JD_TEXT } from '../data/examples'

export default function NewInterviewPage() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const initialResumeId = searchParams.get('resumeId') || ''
  const [resumes, setResumes] = useState<ResumeSummary[]>([])
  const [business, setBusiness] = useState<BusinessEntitlements | null>(null)
  const [resumeId, setResumeId] = useState(initialResumeId)
  const [jdText, setJdText] = useState('')
  const [loading, setLoading] = useState(false)
  const [loadingLabel, setLoadingLabel] = useState('')
  const [loadingResumes, setLoadingResumes] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    Promise.all([resumeApi.list(), businessApi.entitlements()])
      .then(([res, businessRes]) => {
        setResumes(res.data)
        setBusiness(businessRes.data)
        if (!initialResumeId && res.data.length > 0) {
          setResumeId(res.data[0].id)
        }
      })
      .catch((err: any) => setError(err.response?.data?.detail || '简历列表加载失败'))
      .finally(() => setLoadingResumes(false))
  }, [initialResumeId])

  const selectedResume = resumes.find((resume) => resume.id === resumeId)
  const interviewPaywallBlocked = Boolean(
    business?.entitlements.paywall_active && !business.entitlements.can_create_interview,
  )

  const handleStart = async () => {
    if (!resumeId) {
      setError('请先选择简历')
      return
    }
    setLoading(true)
    setLoadingLabel('正在创建面试...')
    setError('')
    try {
      const res = await interviewApi.create(resumeId, jdText.trim() || undefined)
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
      description="选择一份简历，可选关联 JD，系统会结合简历要点和 RAG 岗位知识生成追问题。"
      actions={
        <Button type="button" variant="secondary" onClick={() => navigate('/resumes')}>
          <ArrowLeft size={16} />
          返回工作台
        </Button>
      }
    >
      <div className="mx-auto max-w-3xl space-y-6">
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
          <Card>
            <div className="mb-6 flex items-start justify-between gap-4">
              <div>
                <h2 className="card-title">面试配置</h2>
                <p className="card-subtitle">创建后可先查看全部题目，再逐题作答。</p>
              </div>
              <Badge tone="info">RAG 出题</Badge>
            </div>

            <div className="space-y-5">
              <Field label="选择简历">
                <select
                  value={resumeId}
                  onChange={(event) => setResumeId(event.target.value)}
                  className="select"
                >
                  <option value="">请选择</option>
                  {resumes.map((resume) => (
                    <option key={resume.id} value={resume.id}>
                      {resume.title}
                    </option>
                  ))}
                </select>
              </Field>

              {selectedResume && (
                <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
                  <div className="flex items-center gap-2 font-semibold text-slate-950">
                    <BriefcaseBusiness size={16} />
                    {selectedResume.title}
                  </div>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {selectedResume.template_id ? <Badge tone="info">{selectedResume.template_id}</Badge> : <Badge>未优化</Badge>}
                    {selectedResume.match_score ? <Badge tone="success">{selectedResume.match_score} 匹配</Badge> : null}
                  </div>
                </div>
              )}

              {interviewPaywallBlocked && (
                <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
                  免费模拟面试额度已用完，当前需要升级 Pro 或联系管理员开通权益。
                </div>
              )}

              <Field label="岗位 JD" hint={`${jdText.length}/40000 字符，可选`}>
                <textarea
                  placeholder="粘贴岗位 JD，系统会结合岗位偏好调整出题方向"
                  value={jdText}
                  onChange={(event) => setJdText(event.target.value)}
                  className="textarea min-h-48"
                  maxLength={40000}
                />
              </Field>

              <Button type="button" variant="secondary" className="w-full" onClick={() => setJdText(SAMPLE_JD_TEXT)}>
                填入示例 JD
              </Button>

              <Button type="button" size="lg" className="w-full" onClick={handleStart} disabled={loading || !resumeId || interviewPaywallBlocked}>
                {loading ? <MessageSquareText size={16} /> : <Play size={16} />}
                {loading ? loadingLabel || '处理中...' : interviewPaywallBlocked ? '需升级后创建' : '开始生成面试'}
              </Button>
            </div>
          </Card>
        )}
      </div>
    </AppShell>
  )
}
