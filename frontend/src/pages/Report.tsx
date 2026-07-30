import { useEffect, useMemo, useState } from 'react'
import { useParams, useNavigate } from 'react-router'
import { ArrowLeft, Download, FileText, Gauge, Lightbulb, Target } from 'lucide-react'
import AppShell from '../components/AppShell'
import { Badge, Button, Card, EmptyState, LoadingState, ProgressBar, StatTile } from '../components/ui'
import { interviewApi, InterviewQuestion, InterviewReport } from '../services/interview'
import { businessApi, BusinessEntitlements } from '../services/business'

const scoreLabels: Record<string, string> = {
  technical_accuracy: '技术准确性',
  project_understanding: '项目理解',
  structure_clarity: '表达结构',
  troubleshooting: '问题定位',
  engineering_delivery: '工程落地',
  reflection: '复盘能力',
  completeness: '完整性',
  logic: '逻辑清晰度',
  consistency: '简历一致性',
  conciseness: '表达精炼度',
  depth: '技术/业务深度',
}

const moduleLabels: Record<string, string> = {
  project: '项目深挖',
  internship: '实习经历',
  agent_fundamentals: 'Agent 八股',
  resume: '简历要点',
}

const questionTypeLabels: Record<string, string> = {
  technical_detail: '技术细节',
  troubleshooting: '排查定位',
  tradeoff: '方案取舍',
  metrics_reflection: '结果复盘',
  project_deep_dive: '项目追问',
  internship_deep_dive: '实习追问',
  agent_fundamentals: 'Agent 基础',
  resume_core: '简历要点',
}

function questionSource(question: InterviewQuestion) {
  return question.source_section || (question.point_title || '').replace(/^项目：|^实习：|^Agent 八股：|^简历：/, '')
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

export default function ReportPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [report, setReport] = useState<InterviewReport | null>(null)
  const [business, setBusiness] = useState<BusinessEntitlements | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!id) return
    Promise.all([interviewApi.getReport(id), businessApi.entitlements()])
      .then(([reportRes, businessRes]) => {
        setReport(reportRes.data)
        setBusiness(businessRes.data)
      })
      .catch((err: any) => setError(err.response?.data?.detail || '报告加载失败'))
  }, [id])

  const answeredCount = useMemo(
    () => report?.questions.filter((question) => question.user_answer).length ?? 0,
    [report],
  )
  const totalScore = report?.total_score ?? 0
  const exportPaywallBlocked = Boolean(
    business?.entitlements.paywall_active && !business.entitlements.can_export_report,
  )

  const handleExport = async (format: 'md' | 'docx' | 'pdf') => {
    try {
      if (format === 'md') {
        const res = await interviewApi.exportReport(id!)
        downloadBlob(new Blob([res.data.content], { type: 'text/markdown' }), res.data.filename)
      } else {
        const res = await interviewApi.exportReportFile(id!, format)
        downloadBlob(res.data, `面试报告.${format}`)
      }
      businessApi.entitlements().then((businessRes) => setBusiness(businessRes.data)).catch(() => undefined)
    } catch (err: any) {
      setError(err.response?.data?.detail || '报告导出失败')
    }
  }

  if (!report && !error) return <LoadingState label="正在加载报告" />

  if (!report) {
    return (
      <AppShell title="面试报告" actions={<Button type="button" variant="secondary" onClick={() => navigate('/resumes')}>返回</Button>}>
        <EmptyState title="报告不可用" description={error || '请先完成面试并生成报告。'} />
      </AppShell>
    )
  }

  return (
    <AppShell
      title="面试总结报告"
      description="基于回答记录生成总体评分、分项能力、薄弱点和复习建议。"
      actions={
        <>
          <Button type="button" variant="secondary" onClick={() => navigate('/resumes')}>
            <ArrowLeft size={16} />
            返回工作台
          </Button>
          <Button type="button" onClick={() => handleExport('md')} disabled={exportPaywallBlocked} data-testid="export-report-md-button">
            <Download size={16} />
            {exportPaywallBlocked ? '需升级后导出' : '导出 Markdown'}
          </Button>
          <Button type="button" variant="secondary" onClick={() => handleExport('docx')} disabled={exportPaywallBlocked} data-testid="export-report-docx-button">
            <Download size={16} />
            Word
          </Button>
          <Button type="button" variant="secondary" onClick={() => handleExport('pdf')} disabled={exportPaywallBlocked} data-testid="export-report-pdf-button">
            <Download size={16} />
            PDF
          </Button>
        </>
      }
    >
      <div className="space-y-6" data-testid="report-page">
        {error && <div className="rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div>}
        {exportPaywallBlocked && (
          <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
            免费报告导出额度已用完，请升级 Pro 或联系管理员开通权益。
          </div>
        )}

        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <StatTile label="总体评分" value={totalScore} meta="百分制报告评分" icon={<Gauge size={18} />} />
          <StatTile label="已答题目" value={answeredCount} meta={`总题数 ${report.questions.length}`} icon={<FileText size={18} />} />
          <StatTile label="薄弱点" value={report.weak_points?.length || 0} meta="建议优先复盘" icon={<Target size={18} />} />
        </div>

        <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
          <Card>
            <div className="mb-5">
              <h2 className="card-title">分项能力</h2>
              <p className="card-subtitle">技术、项目、排查、交付和复盘越均衡，面试表达越稳定。</p>
            </div>
            <div className="space-y-4">
              {Object.entries(report.dimension_scores || {}).map(([key, score]) => {
                const numericScore = Number(score)
                return (
                  <div key={key}>
                    <div className="mb-2 flex items-center justify-between text-sm">
                      <span className="font-semibold text-slate-700">{scoreLabels[key] || key}</span>
                      <span className="text-slate-500">{numericScore}/10</span>
                    </div>
                    <ProgressBar value={numericScore * 10} />
                  </div>
                )
              })}
            </div>
          </Card>

          <Card>
            <div className="mb-5 flex items-start justify-between gap-4">
              <div>
                <h2 className="card-title">表现总结</h2>
                <p className="card-subtitle">用于复盘本次面试的共性表现。</p>
              </div>
              <Badge tone={totalScore >= 80 ? 'success' : totalScore >= 60 ? 'warning' : 'danger'}>
                {totalScore >= 80 ? '稳定' : totalScore >= 60 ? '可提升' : '需补强'}
              </Badge>
            </div>
            <p className="text-sm leading-7 text-slate-700">{report.summary}</p>
          </Card>
        </div>

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <Card>
            <div className="mb-5 flex items-center gap-2">
              <Target size={18} className="text-rose-600" />
              <h2 className="card-title">薄弱点</h2>
            </div>
            <div className="space-y-3">
              {report.weak_points?.map((point, index) => (
                <div key={point} className="rounded-lg border border-rose-100 bg-rose-50 px-4 py-3 text-sm leading-6 text-rose-800">
                  <span className="font-bold">{index + 1}. </span>
                  {point}
                </div>
              ))}
            </div>
          </Card>

          <Card>
            <div className="mb-5 flex items-center gap-2">
              <Lightbulb size={18} className="text-amber-600" />
              <h2 className="card-title">复习建议</h2>
            </div>
            <div className="space-y-3">
              {report.suggestions?.map((suggestion, index) => (
                <div key={suggestion} className="rounded-lg border border-amber-100 bg-amber-50 px-4 py-3 text-sm leading-6 text-amber-900">
                  <span className="font-bold">{index + 1}. </span>
                  {suggestion}
                </div>
              ))}
            </div>
          </Card>
        </div>

        <Card>
          <div className="mb-5">
            <h2 className="card-title">答题详情</h2>
            <p className="card-subtitle">按题目回看回答、评分和精简答案。</p>
          </div>
          <div className="space-y-4">
            {report.questions.map((question, index) => (
              <div key={question.id} className="rounded-lg border border-slate-200 bg-white p-4">
                <div className="mb-2 flex flex-wrap items-center gap-2">
                  <Badge tone="neutral">Q{index + 1}</Badge>
                  {question.total_score !== null && <Badge tone="info">{question.total_score} 分</Badge>}
                  <Badge>{moduleLabels[question.module] || '简历要点'}</Badge>
                  {question.question_type && <Badge tone="neutral">{questionTypeLabels[question.question_type] || question.question_type}</Badge>}
                  {questionSource(question) && <Badge tone="neutral">{questionSource(question)}</Badge>}
                </div>
                <div className="font-semibold leading-7 text-slate-950">{question.question}</div>
                <div className="mt-3 rounded-md bg-slate-50 p-3 text-sm leading-6 text-slate-600">
                  {question.user_answer || '未作答'}
                </div>
                {question.refined_answer && (
                  <div className="mt-3 rounded-md border border-emerald-200 bg-emerald-50 p-3 text-sm leading-6 text-emerald-800">
                    <span className="font-semibold">精简答案：</span>
                    {question.refined_answer}
                  </div>
                )}
              </div>
            ))}
          </div>
        </Card>
      </div>
    </AppShell>
  )
}
