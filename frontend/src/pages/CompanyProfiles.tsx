import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router'
import { BookOpenCheck, Building2, ChevronLeft, ChevronRight, Layers3, Target } from 'lucide-react'
import AppShell from '../components/AppShell'
import { Badge, Button, Card, EmptyState, Field, LoadingState, StatTile } from '../components/ui'
import {
  companyProfileApi,
  type CompanyInterviewProfile,
  type CompanyProfileList,
} from '../services/companyProfiles'

const confidenceLabels = { low: '样本较少', medium: '样本一般', high: '样本充分' }
const difficultyLabels: Record<string, string> = {
  easy: '简单',
  medium: '中等',
  hard: '较难',
  unknown: '未知',
}

function confidenceTone(value: string): 'neutral' | 'success' | 'warning' | 'danger' | 'info' {
  if (value === 'high') return 'success'
  if (value === 'medium') return 'info'
  return 'warning'
}

export default function CompanyProfilesPage() {
  const navigate = useNavigate()
  const [payload, setPayload] = useState<CompanyProfileList | null>(null)
  const [selected, setSelected] = useState<CompanyInterviewProfile | null>(null)
  const [company, setCompany] = useState('')
  const [position, setPosition] = useState('')
  const [roundType, setRoundType] = useState('')
  const [topic, setTopic] = useState('')
  const [offset, setOffset] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const limit = 20

  useEffect(() => {
    let cancelled = false
    const timer = window.setTimeout(() => {
      setError('')
      companyProfileApi.list({
        company: company.trim() || undefined,
        position: position.trim() || undefined,
        round_type: roundType.trim() || undefined,
        topic: topic.trim() || undefined,
        limit,
        offset,
      })
        .then((res) => {
          if (cancelled) return
          setPayload(res.data)
          setSelected((current) => {
            if (current && res.data.items.some((item) => item.id === current.id)) return current
            return res.data.items[0] || null
          })
        })
        .catch((err: any) => !cancelled && setError(err.response?.data?.detail || '公司面试参考加载失败'))
        .finally(() => !cancelled && setLoading(false))
    }, 250)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [company, position, roundType, topic, offset])

  const openProfile = async (profile: CompanyInterviewProfile) => {
    setSelected(profile)
    try {
      const res = await companyProfileApi.get(profile.id)
      setSelected(res.data)
    } catch (err: any) {
      setError(err.response?.data?.detail || '详情加载失败')
    }
  }

  if (loading && !payload) return <LoadingState label="正在加载公司面试参考" />

  return (
    <AppShell
      title="公司面试参考"
      description="按公司和岗位整理公开面经中的常见轮次、问题和技术主题。"
      actions={
        <Button type="button" variant="secondary" onClick={() => navigate('/experiences')}>
          真实面经
        </Button>
      }
    >
      <div className="space-y-6">
        {error && <div className="rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div>}

        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <StatTile label="公司岗位" value={payload?.total ?? 0} meta="当前可见范围" icon={<Building2 size={18} />} />
          <StatTile label="面经样本" value={payload?.items.reduce((sum, item) => sum + item.interview_count, 0) ?? 0} meta="当前页累计" icon={<Layers3 size={18} />} />
          <StatTile label="高频问题" value={payload?.items.reduce((sum, item) => sum + item.frequent_questions.length, 0) ?? 0} meta="当前页已聚合" icon={<BookOpenCheck size={18} />} />
        </div>

        <Card>
          <div className="mb-4">
            <h2 className="card-title">筛选公司和岗位</h2>
            <p className="card-subtitle">公司和岗位用于精确匹配，轮次与主题用于训练方向筛选。</p>
          </div>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
            <Field label="公司">
              <input className="input" value={company} onChange={(event) => { setCompany(event.target.value); setOffset(0) }} placeholder="公司名称" />
            </Field>
            <Field label="岗位">
              <input className="input" value={position} onChange={(event) => { setPosition(event.target.value); setOffset(0) }} placeholder="AI Agent 开发" />
            </Field>
            <Field label="轮次">
              <select className="select" value={roundType} onChange={(event) => { setRoundType(event.target.value); setOffset(0) }}>
                <option value="">全部轮次</option>
                <option value="technical_first">技术一面</option>
                <option value="project_deep_dive">项目深挖</option>
                <option value="system_design">系统设计</option>
                <option value="hr_behavior">HR / 行为面</option>
              </select>
            </Field>
            <Field label="技术主题">
              <input className="input" value={topic} onChange={(event) => { setTopic(event.target.value); setOffset(0) }} placeholder="RAG / 工程化" />
            </Field>
          </div>
        </Card>

        {!payload?.items.length ? (
          <EmptyState title="暂无相关记录" description="发布并授权使用的面经会汇总在这里。" />
        ) : (
          <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(280px,0.75fr)_minmax(0,1.25fr)]">
            <Card className="h-fit">
              <div className="space-y-2">
                {payload.items.map((profile) => (
                  <button
                    key={profile.id}
                    type="button"
                    onClick={() => openProfile(profile)}
                    className={`w-full rounded-md border p-3 text-left transition ${selected?.id === profile.id ? 'border-slate-700 bg-slate-50' : 'border-slate-200 bg-white hover:bg-slate-50'}`}
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge tone={profile.scope === 'organization' ? 'info' : 'neutral'}>{profile.scope === 'organization' ? '当前组织' : '公开'}</Badge>
                      <Badge tone={confidenceTone(profile.profile_confidence)}>{confidenceLabels[profile.profile_confidence]}</Badge>
                    </div>
                    <div className="mt-2 font-semibold text-slate-950">{profile.company_name}</div>
                    <div className="mt-1 text-sm text-slate-600">{profile.position_name}</div>
                    <div className="mt-2 text-xs text-slate-500">{profile.interview_count} 份面经 · {profile.frequent_questions.length} 个问题簇</div>
                  </button>
                ))}
              </div>
              <div className="mt-4 flex items-center justify-between gap-3">
                <Button type="button" size="sm" variant="secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - limit))} aria-label="上一页">
                  <ChevronLeft size={16} />
                </Button>
                <span className="text-xs text-slate-500">{offset + 1}-{Math.min(offset + limit, payload.total)} / {payload.total}</span>
                <Button type="button" size="sm" variant="secondary" disabled={offset + limit >= payload.total} onClick={() => setOffset(offset + limit)} aria-label="下一页">
                  <ChevronRight size={16} />
                </Button>
              </div>
            </Card>

            <Card>
              {selected ? (
                <div className="space-y-6">
                  <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start">
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge tone="info">{selected.company_name}</Badge>
                        <Badge>{selected.position_name}</Badge>
                      </div>
                      <h2 className="mt-3 text-xl font-bold text-slate-950">常见面试流程</h2>
                      <p className="mt-1 text-sm text-slate-500">{selected.interview_count} 份有效面经 · 数据版本 {selected.profile_version}</p>
                    </div>
                    <Button type="button" onClick={() => navigate(`/interviews/new?company=${encodeURIComponent(selected.company_name)}&position=${encodeURIComponent(selected.position_name)}`)}>
                      <Target size={16} />
                      按此参考练习
                    </Button>
                  </div>

                  <section>
                    <h3 className="text-sm font-bold text-slate-950">常见轮次</h3>
                    <div className="mt-3 flex flex-wrap gap-2">
                      {selected.common_rounds.map((item) => <Badge key={item.round_type} tone="info">{item.name} · {item.source_count}</Badge>)}
                      {!selected.common_rounds.length && <span className="text-sm text-slate-500">暂无结构化轮次</span>}
                    </div>
                  </section>

                  <section>
                    <h3 className="text-sm font-bold text-slate-950">高频技术主题</h3>
                    <div className="mt-3 flex flex-wrap gap-2">
                      {selected.technical_topics.map((item) => <Badge key={item.topic_key} tone="warning">{item.name} · {item.source_count}</Badge>)}
                    </div>
                  </section>

                  <section>
                    <h3 className="text-sm font-bold text-slate-950">难度分布</h3>
                    <div className="mt-3 flex flex-wrap gap-2">
                      {Object.entries(selected.difficulty_distribution).map(([key, count]) => <Badge key={key}>{difficultyLabels[key] || key} · {count}</Badge>)}
                    </div>
                  </section>

                  <section>
                    <h3 className="text-sm font-bold text-slate-950">高频问题</h3>
                    <div className="mt-3 divide-y divide-slate-100 border-y border-slate-100">
                      {selected.frequent_questions.slice(0, 12).map((question, index) => (
                        <div key={`${question.canonical_question}-${index}`} className="py-4">
                          <div className="flex flex-wrap items-center gap-2">
                            <Badge tone="neutral">{question.source_count} 份来源</Badge>
                            <Badge>{difficultyLabels[question.difficulty] || question.difficulty}</Badge>
                            {question.topics.slice(0, 3).map((item) => <Badge key={item} tone="info">{item}</Badge>)}
                          </div>
                          <p className="mt-2 text-sm font-semibold leading-6 text-slate-900">{question.canonical_question}</p>
                        </div>
                      ))}
                    </div>
                  </section>
                </div>
              ) : (
                <EmptyState title="选择一条公司和岗位记录" />
              )}
            </Card>
          </div>
        )}
      </div>
    </AppShell>
  )
}
