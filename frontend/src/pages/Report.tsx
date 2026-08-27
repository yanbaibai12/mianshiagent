import { useEffect, useMemo, useState } from 'react'
import { useParams, useNavigate } from 'react-router'
import { ArrowLeft, Building2, CalendarCheck2, Download, FileText, Gauge, Lightbulb, Target } from 'lucide-react'
import AppShell from '../components/AppShell'
import { Badge, Button, Card, EmptyState, LoadingState, ProgressBar, StatTile } from '../components/ui'
import { interviewApi, InterviewQuestion, InterviewReport } from '../services/interview'
import { trainingPlanApi } from '../services/trainingPlans'

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
  system_design: '系统设计',
  behavioral: 'HR / 行为面',
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
  system_design: '系统设计',
  behavioral_star: 'STAR 行为题',
  resume_core: '简历要点',
}

const hireSignalLabels: Record<string, string> = {
  strong: '强推荐',
  positive: '正向',
  borderline: '边缘通过',
  weak: '风险较高',
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
  const [error, setError] = useState('')
  const [generatingPlan, setGeneratingPlan] = useState(false)

  useEffect(() => {
    if (!id) return
    interviewApi.getReport(id)
      .then((reportRes) => setReport(reportRes.data))
      .catch((err: any) => setError(err.response?.data?.detail || '报告加载失败'))
  }, [id])

  const answeredCount = useMemo(
    () => report?.questions.filter((question) => question.user_answer).length ?? 0,
    [report],
  )
  const totalScore = report?.total_score ?? 0
  const templateInfo = report?.report_details?.interview_template || null
  const companyProfile = report?.company_profile_snapshot || report?.report_details?.company_profile || null
  const handleExport = async (format: 'md' | 'docx' | 'pdf') => {
    try {
      if (format === 'md') {
        const res = await interviewApi.exportReport(id!)
        downloadBlob(new Blob([res.data.content], { type: 'text/markdown' }), res.data.filename)
      } else {
        const res = await interviewApi.exportReportFile(id!, format)
        downloadBlob(res.data, `面试报告.${format}`)
      }
    } catch (err: any) {
      setError(err.response?.data?.detail || '报告导出失败')
    }
  }

  const handleGeneratePlan = async () => {
    if (!id) return
    setGeneratingPlan(true)
    setError('')
    try {
      await trainingPlanApi.generate(id)
      navigate('/training-plan')
    } catch (err: any) {
      setError(err.response?.data?.detail || '训练计划生成失败')
    } finally {
      setGeneratingPlan(false)
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
          <Button type="button" variant="success" disabled={generatingPlan} onClick={handleGeneratePlan}>
            <CalendarCheck2 size={16} />
            {generatingPlan ? '生成中...' : '生成本周训练计划'}
          </Button>
          <Button type="button" onClick={() => handleExport('md')} data-testid="export-report-md-button">
            <Download size={16} />
            导出 Markdown
          </Button>
          <Button type="button" variant="secondary" onClick={() => handleExport('docx')} data-testid="export-report-docx-button">
            <Download size={16} />
            Word
          </Button>
          <Button type="button" variant="secondary" onClick={() => handleExport('pdf')} data-testid="export-report-pdf-button">
            <Download size={16} />
            PDF
          </Button>
        </>
      }
    >
      <div className="space-y-6" data-testid="report-page">
        {error && <div className="rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div>}
        <Card>
          <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-start">
            <div>
              <div className="mb-2 flex flex-wrap items-center gap-2">
                <Badge tone="info">{report.interview_template_name || templateInfo?.name || '综合面'}</Badge>
                {report.template_config_snapshot?.use_training_profile && <Badge tone="warning">结合掌握记录</Badge>}
              </div>
              <h2 className="card-title">本轮面试重点</h2>
              <p className="card-subtitle">{templateInfo?.scenario || report.template_config_snapshot?.scenario || '混合项目、技术和表达能力复盘。'}</p>
            </div>
            <div className="flex flex-wrap gap-2 lg:max-w-xl lg:justify-end">
              {(report.report_details?.template_focus || report.template_config_snapshot?.report_focus || []).slice(0, 6).map((focus: string) => (
                <Badge key={focus}>{focus}</Badge>
              ))}
            </div>
          </div>
        </Card>

        {(companyProfile?.matched_company || report.target_company) && (
          <div className="border-y border-slate-200 bg-slate-50 px-4 py-4">
            <div className="flex flex-col justify-between gap-3 lg:flex-row lg:items-center">
              <div className="flex items-start gap-3">
                <Building2 size={18} className="mt-0.5 shrink-0 text-slate-600" />
                <div>
                  <div className="font-semibold text-slate-950">
                    {companyProfile?.matched_company || report.target_company} · {companyProfile?.matched_position || report.target_position || '目标岗位'}
                  </div>
                  <p className="mt-1 text-sm text-slate-600">
                    {companyProfile?.source_count
                      ? `本轮参考 ${companyProfile.source_count} 份真实面经，样本情况${companyProfile.profile_confidence === 'high' ? '充分' : companyProfile.profile_confidence === 'medium' ? '一般' : '较少'}`
                      : '本轮没有匹配到相关面经，将结合简历、JD、面试轮次和掌握记录出题。'}
                  </p>
                </div>
              </div>
              <div className="flex flex-wrap gap-2 lg:justify-end">
                {(companyProfile?.matched_topics || []).slice(0, 5).map((item: any) => <Badge key={item.topic_key || item.name}>{item.name}</Badge>)}
              </div>
            </div>
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

        {report.report_details && (
          <div className="grid grid-cols-1 gap-6 xl:grid-cols-[0.9fr_1.1fr]" data-testid="report-details-panel">
            <Card>
              <div className="mb-5">
                <h2 className="card-title">面试信号</h2>
                <p className="card-subtitle">结合总分、模块表现和回答证据给出的综合判断。</p>
              </div>
              <div className="flex flex-wrap items-center gap-3">
                <Badge tone={report.report_details.hire_signal === 'strong' || report.report_details.hire_signal === 'positive' ? 'success' : report.report_details.hire_signal === 'borderline' ? 'warning' : 'danger'}>
                  {hireSignalLabels[report.report_details.hire_signal] || '待判断'}
                </Badge>
                {Object.entries(report.report_details.module_scores || {}).map(([module, score]: [string, any]) => (
                  <div key={module} className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm">
                    <span className="font-semibold text-slate-900">{moduleLabels[module] || module}</span>
                    <span className="ml-2 text-slate-500">{String(score)} 分</span>
                  </div>
                ))}
              </div>
              {Boolean(Object.keys(report.report_details.template_dimension_scores || {}).length) && (
                <div className="mt-5 grid gap-3 md:grid-cols-2">
                  {Object.entries(report.report_details.template_dimension_scores || {}).map(([key, score]: [string, any]) => {
                    const dimension = (report.report_details.template_scoring_dimensions || []).find((item: any) => item.key === key)
                    return (
                      <div key={key} className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm">
                        <span className="font-semibold text-slate-900">{dimension?.label || scoreLabels[key] || key}</span>
                        <span className="ml-2 text-slate-500">{String(score)} 分</span>
                      </div>
                    )
                  })}
                </div>
              )}
              {Boolean(report.report_details.strongest_evidence?.length) && (
                <div className="mt-5 space-y-2">
                  {report.report_details.strongest_evidence.slice(0, 3).map((item: any, index: number) => (
                    <div key={index} className="rounded-md border border-slate-200 bg-slate-50 p-3 text-sm leading-6 text-slate-700">
                      <span className="font-semibold">{item.source}：</span>
                      {item.snippet}
                    </div>
                  ))}
                </div>
              )}
            </Card>

            <Card>
              <div className="mb-5">
                <h2 className="card-title">专项训练</h2>
                <p className="card-subtitle">针对本次重复缺口生成下一轮训练动作。</p>
              </div>
              <div className="grid gap-3 lg:grid-cols-2">
                {(report.report_details.next_round_suggestions || []).slice(0, 4).map((item: string, index: number) => (
                  <div key={`next-round-${index}`} className="rounded-md border border-slate-200 bg-slate-50 p-3 text-sm leading-6 text-slate-700">
                    下一轮：{item}
                  </div>
                ))}
                {(report.report_details.repeated_gaps || []).slice(0, 4).map((gap: string, index: number) => (
                  <div key={`gap-${index}`} className="rounded-md border border-rose-100 bg-rose-50 p-3 text-sm leading-6 text-rose-800">
                    {gap}
                  </div>
                ))}
                {(report.report_details.follow_up_training_plan || []).slice(0, 4).map((action: string, index: number) => (
                  <div key={`action-${index}`} className="rounded-md border border-amber-100 bg-amber-50 p-3 text-sm leading-6 text-amber-900">
                    {action}
                  </div>
                ))}
              </div>
            </Card>
          </div>
        )}

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
                {Boolean(question.evidence?.length) && (
                  <div className="mt-3 rounded-md border border-slate-200 border-l-4 bg-slate-50 p-3 text-sm leading-6 text-slate-700" style={{ borderLeftColor: '#436052' }}>
                    <div className="font-semibold text-slate-950">来源依据</div>
                    {question.evidence?.slice(0, 2).map((item, evidenceIndex) => (
                      <div key={`${item.source_title}-${evidenceIndex}`} className="mt-1">
                        {item.source_section} / {item.source_title}：{item.source_snippet}
                      </div>
                    ))}
                  </div>
                )}
                <div className="mt-3 rounded-md bg-slate-50 p-3 text-sm leading-6 text-slate-600">
                  {question.user_answer || '未作答'}
                </div>
                {question.score_details && (
                  <div className="mt-3 grid gap-3 lg:grid-cols-2">
                    {Object.entries(question.score_details).map(([key, detail]: [string, any]) => (
                      <div key={key} className="rounded-md border border-slate-200 bg-white p-3 text-sm leading-6 text-slate-700">
                        <div className="font-semibold text-slate-950">{scoreLabels[key] || detail.label || key}：{detail.score}</div>
                        {detail.issue && <div className="mt-1">扣分点：{detail.issue}</div>}
                        {detail.suggestion && <div className="mt-1 text-slate-700">建议：{detail.suggestion}</div>}
                      </div>
                    ))}
                  </div>
                )}
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
