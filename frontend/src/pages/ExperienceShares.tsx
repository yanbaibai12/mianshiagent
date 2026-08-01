import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router'
import { BookOpenCheck, Building2, ChevronLeft, ChevronRight, Eye, Heart, MessageSquareText, PlusCircle, Send, Trash2 } from 'lucide-react'
import AppShell from '../components/AppShell'
import { Badge, Button, Card, EmptyState, Field, LoadingState, StatTile } from '../components/ui'
import {
  communityApi,
  type InterviewExperienceCreatePayload,
  type InterviewExperienceList,
  type InterviewExperienceShare,
} from '../services/community'

const difficultyLabel: Record<string, string> = {
  easy: '轻松',
  medium: '中等',
  hard: '较难',
  unknown: '未知',
}

const resultLabel: Record<string, string> = {
  offer: 'Offer',
  passed: '通过',
  failed: '未通过',
  pending: '待反馈',
  unknown: '未知',
}

const visibilityLabel: Record<string, string> = {
  public: '公开社区',
  organization: '当前组织',
  private: '仅自己',
}

function difficultyTone(value: string): 'neutral' | 'success' | 'warning' | 'danger' | 'info' {
  if (value === 'easy') return 'success'
  if (value === 'hard') return 'danger'
  if (value === 'medium') return 'warning'
  return 'neutral'
}

function resultTone(value: string): 'neutral' | 'success' | 'warning' | 'danger' | 'info' {
  if (value === 'offer') return 'success'
  if (value === 'passed') return 'info'
  if (value === 'failed') return 'danger'
  if (value === 'pending') return 'warning'
  return 'neutral'
}

function splitLines(value: string) {
  return value
    .split(/[\n,，;；]+/)
    .map((item) => item.trim())
    .filter(Boolean)
}

const emptyForm = {
  company: '',
  position: '',
  city: '',
  interview_date: '',
  rounds: '',
  difficulty: 'medium' as InterviewExperienceCreatePayload['difficulty'],
  result: 'unknown' as InterviewExperienceCreatePayload['result'],
  tags: '',
  questions: '',
  process: '',
  content: '',
  visibility: 'public' as InterviewExperienceCreatePayload['visibility'],
  is_anonymous: true,
  allow_profile_usage: true,
}

export default function ExperienceSharesPage() {
  const navigate = useNavigate()
  const [payload, setPayload] = useState<InterviewExperienceList | null>(null)
  const [selected, setSelected] = useState<InterviewExperienceShare | null>(null)
  const [query, setQuery] = useState('')
  const [tag, setTag] = useState('')
  const [difficulty, setDifficulty] = useState('')
  const [result, setResult] = useState('')
  const [offset, setOffset] = useState(0)
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState(emptyForm)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  const limit = 20

  const loadExperiences = async () => {
    setError('')
    const res = await communityApi.listExperiences({
      q: query.trim() || undefined,
      tag: tag.trim() || undefined,
      difficulty: difficulty || undefined,
      result: result || undefined,
      limit,
      offset,
    })
    setPayload(res.data)
    setSelected((current) => {
      if (current && res.data.items.some((item) => item.id === current.id)) return current
      return res.data.items[0] || null
    })
    return res.data
  }

  useEffect(() => {
    setLoading(true)
    loadExperiences()
      .catch((err: any) => setError(err.response?.data?.detail || '真实面经加载失败'))
      .finally(() => setLoading(false))
  }, [query, tag, difficulty, result, offset])

  const openDetail = async (item: InterviewExperienceShare) => {
    setShowForm(false)
    setError('')
    try {
      const res = await communityApi.getExperience(item.id)
      setSelected(res.data)
      await loadExperiences()
    } catch (err: any) {
      setError(err.response?.data?.detail || '面经详情加载失败')
    }
  }

  const submitExperience = async (event: React.FormEvent) => {
    event.preventDefault()
    setSaving(true)
    setError('')
    setMessage('')
    try {
      const res = await communityApi.createExperience({
        company: form.company.trim(),
        position: form.position.trim(),
        city: form.city.trim() || null,
        interview_date: form.interview_date || null,
        rounds: form.rounds.trim() || null,
        difficulty: form.difficulty,
        result: form.result,
        tags: splitLines(form.tags),
        questions: splitLines(form.questions),
        process: form.process.trim() || null,
        content: form.content.trim(),
        visibility: form.visibility,
        is_anonymous: form.is_anonymous,
        allow_profile_usage: form.allow_profile_usage,
      })
      setForm(emptyForm)
      setShowForm(false)
      setSelected(res.data)
      setMessage('面经已发布')
      await loadExperiences()
    } catch (err: any) {
      setError(err.response?.data?.detail || '面经发布失败')
    } finally {
      setSaving(false)
    }
  }

  const likeSelected = async () => {
    if (!selected) return
    setError('')
    try {
      const res = await communityApi.likeExperience(selected.id)
      setSelected(res.data)
      await loadExperiences()
    } catch (err: any) {
      setError(err.response?.data?.detail || '点赞失败')
    }
  }

  const deleteSelected = async () => {
    if (!selected || !selected.can_edit) return
    setError('')
    try {
      await communityApi.deleteExperience(selected.id)
      setSelected(null)
      setMessage('面经已删除')
      await loadExperiences()
    } catch (err: any) {
      setError(err.response?.data?.detail || '删除失败')
    }
  }

  const resetFilters = () => {
    setQuery('')
    setTag('')
    setDifficulty('')
    setResult('')
    setOffset(0)
  }

  if (loading && !payload) return <LoadingState label="正在加载真实面经" />

  return (
    <AppShell
      title="真实面经"
      description="沉淀真实公司、岗位、轮次、题目和复盘经验，辅助后续投递与面试训练。"
      actions={
        <div className="flex flex-wrap gap-2">
          <Button type="button" variant="secondary" onClick={() => navigate('/agent-questions')}>
            Agent 八股题
          </Button>
          <Button type="button" onClick={() => setShowForm(true)}>
            <PlusCircle size={16} />
            发布面经
          </Button>
        </div>
      }
    >
      <div className="space-y-6">
        {error && <div className="rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div>}
        {message && <div className="rounded-md border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{message}</div>}

        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
          <StatTile label="面经数量" value={payload?.total ?? '-'} meta="当前可见范围" icon={<MessageSquareText size={18} />} />
          <StatTile label="Offer 分享" value={payload?.items.filter((item) => item.result === 'offer').length ?? '-'} meta="当前页统计" icon={<Building2 size={18} />} />
          <StatTile label="题目记录" value={payload?.items.reduce((sum, item) => sum + item.questions.length, 0) ?? '-'} meta="当前页累计" icon={<BookOpenCheck size={18} />} />
          <StatTile label="浏览次数" value={payload?.items.reduce((sum, item) => sum + item.view_count, 0) ?? '-'} meta="当前页累计" icon={<Eye size={18} />} />
        </div>

        <Card>
          <div className="mb-4 flex flex-col justify-between gap-3 lg:flex-row lg:items-start">
            <div>
              <h2 className="card-title">筛选面经</h2>
              <p className="card-subtitle">按公司、岗位、标签、结果和难度缩小范围。</p>
            </div>
            {(query || tag || difficulty || result) && (
              <Button type="button" size="sm" variant="secondary" onClick={resetFilters}>
                清空筛选
              </Button>
            )}
          </div>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
            <Field label="关键词">
              <input
                className="input"
                value={query}
                onChange={(event) => {
                  setQuery(event.target.value)
                  setOffset(0)
                }}
                placeholder="公司 / 岗位 / 技术点"
              />
            </Field>
            <Field label="标签">
              <input
                className="input"
                value={tag}
                onChange={(event) => {
                  setTag(event.target.value)
                  setOffset(0)
                }}
                placeholder="RAG / 后端 / 实习"
              />
            </Field>
            <Field label="结果">
              <select
                className="select"
                value={result}
                onChange={(event) => {
                  setResult(event.target.value)
                  setOffset(0)
                }}
              >
                <option value="">全部结果</option>
                <option value="offer">Offer</option>
                <option value="passed">通过</option>
                <option value="failed">未通过</option>
                <option value="pending">待反馈</option>
                <option value="unknown">未知</option>
              </select>
            </Field>
            <Field label="难度">
              <select
                className="select"
                value={difficulty}
                onChange={(event) => {
                  setDifficulty(event.target.value)
                  setOffset(0)
                }}
              >
                <option value="">全部难度</option>
                <option value="easy">轻松</option>
                <option value="medium">中等</option>
                <option value="hard">较难</option>
                <option value="unknown">未知</option>
              </select>
            </Field>
          </div>
        </Card>

        <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_430px]">
          <Card>
            <div className="mb-5 flex flex-col justify-between gap-3 lg:flex-row lg:items-center">
              <div>
                <h2 className="card-title">面经列表</h2>
                <p className="card-subtitle">共 {payload?.total || 0} 条，当前显示 {payload?.items.length || 0} 条。</p>
              </div>
              <div className="flex items-center gap-2">
                <Button type="button" size="sm" variant="secondary" onClick={() => setOffset(Math.max(0, offset - limit))} disabled={offset === 0}>
                  <ChevronLeft size={14} />
                  上一页
                </Button>
                <Button type="button" size="sm" variant="secondary" onClick={() => setOffset(offset + limit)} disabled={!payload || offset + limit >= payload.total}>
                  下一页
                  <ChevronRight size={14} />
                </Button>
              </div>
            </div>
            <div className="space-y-3">
              {payload?.items.map((item) => (
                <button
                  type="button"
                  key={item.id}
                  className={`block w-full rounded-lg border p-4 text-left transition ${
                    selected?.id === item.id && !showForm
                      ? 'border-slate-700 bg-slate-50 ring-1 ring-slate-200'
                      : 'border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50'
                  }`}
                  onClick={() => openDetail(item)}
                >
                  <div className="mb-2 flex flex-wrap items-center gap-2">
                    <Badge tone={resultTone(item.result)}>{resultLabel[item.result]}</Badge>
                    <Badge tone={difficultyTone(item.difficulty)}>{difficultyLabel[item.difficulty]}</Badge>
                    <Badge tone="neutral">{visibilityLabel[item.visibility]}</Badge>
                  </div>
                  <div className="font-semibold leading-6 text-slate-950">{item.company} · {item.position}</div>
                  <div className="mt-1 text-xs text-slate-500">
                    {item.author_label} · {item.city || '城市未知'} · {item.interview_date || '日期未知'}
                  </div>
                  <p className="mt-2 line-clamp-2 text-sm leading-6 text-slate-600">{item.content}</p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {item.tags.slice(0, 5).map((itemTag) => <Badge key={itemTag} tone="info">{itemTag}</Badge>)}
                  </div>
                </button>
              ))}
              {payload?.items.length === 0 && <EmptyState title="暂无面经" description="发布第一条真实面经，或调整筛选条件。" />}
            </div>
          </Card>

          <Card>
            {showForm ? (
              <form onSubmit={submitExperience} className="space-y-4">
                <div>
                  <h2 className="card-title">发布面经</h2>
                  <p className="card-subtitle">正文会自动脱敏邮箱、手机号和 Key 样式文本。</p>
                </div>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <Field label="公司">
                    <input className="input" value={form.company} onChange={(event) => setForm({ ...form, company: event.target.value })} required maxLength={160} />
                  </Field>
                  <Field label="岗位">
                    <input className="input" value={form.position} onChange={(event) => setForm({ ...form, position: event.target.value })} required maxLength={200} />
                  </Field>
                  <Field label="城市">
                    <input className="input" value={form.city} onChange={(event) => setForm({ ...form, city: event.target.value })} maxLength={80} />
                  </Field>
                  <Field label="面试日期">
                    <input className="input" type="date" value={form.interview_date} onChange={(event) => setForm({ ...form, interview_date: event.target.value })} />
                  </Field>
                  <Field label="结果">
                    <select className="select" value={form.result} onChange={(event) => setForm({ ...form, result: event.target.value as InterviewExperienceCreatePayload['result'] })}>
                      <option value="unknown">未知</option>
                      <option value="pending">待反馈</option>
                      <option value="passed">通过</option>
                      <option value="offer">Offer</option>
                      <option value="failed">未通过</option>
                    </select>
                  </Field>
                  <Field label="难度">
                    <select className="select" value={form.difficulty} onChange={(event) => setForm({ ...form, difficulty: event.target.value as InterviewExperienceCreatePayload['difficulty'] })}>
                      <option value="easy">轻松</option>
                      <option value="medium">中等</option>
                      <option value="hard">较难</option>
                      <option value="unknown">未知</option>
                    </select>
                  </Field>
                </div>
                <Field label="轮次">
                  <input className="input" value={form.rounds} onChange={(event) => setForm({ ...form, rounds: event.target.value })} placeholder="一面 / 二面 / HR 面" maxLength={200} />
                </Field>
                <Field label="标签">
                  <input className="input" value={form.tags} onChange={(event) => setForm({ ...form, tags: event.target.value })} placeholder="RAG，后端，实习" />
                </Field>
                <Field label="被问到的问题">
                  <textarea className="textarea min-h-28" value={form.questions} onChange={(event) => setForm({ ...form, questions: event.target.value })} placeholder="每行一个问题" />
                </Field>
                <Field label="流程记录">
                  <textarea className="textarea min-h-24" value={form.process} onChange={(event) => setForm({ ...form, process: event.target.value })} maxLength={4000} />
                </Field>
                <Field label="复盘正文" hint={`${form.content.length}/12000 字符`}>
                  <textarea className="textarea min-h-40" value={form.content} onChange={(event) => setForm({ ...form, content: event.target.value })} required maxLength={12000} />
                </Field>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <Field label="可见范围">
                    <select className="select" value={form.visibility} onChange={(event) => setForm({ ...form, visibility: event.target.value as InterviewExperienceCreatePayload['visibility'] })}>
                      <option value="public">公开社区</option>
                      <option value="organization">当前组织</option>
                      <option value="private">仅自己</option>
                    </select>
                  </Field>
                  <label className="flex items-center gap-2 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-semibold text-slate-700">
                    <input type="checkbox" checked={form.is_anonymous} onChange={(event) => setForm({ ...form, is_anonymous: event.target.checked })} />
                    匿名展示
                  </label>
                </div>
                <label className="flex items-start gap-3 rounded-md border border-slate-200 bg-slate-50 px-3 py-3 text-sm text-slate-800">
                  <input
                    type="checkbox"
                    className="mt-1"
                    checked={form.allow_profile_usage}
                    onChange={(event) => setForm({ ...form, allow_profile_usage: event.target.checked })}
                  />
                  <span>
                    <span className="block font-semibold">允许用于公司面试参考</span>
                    <span className="mt-1 block text-xs leading-5 text-slate-500">只汇总脱敏后的公司、岗位、轮次、主题和问题统计；仅自己可见的面经不会参与。</span>
                  </span>
                </label>
                <div className="flex gap-2">
                  <Button type="submit" className="flex-1" disabled={saving || !form.company.trim() || !form.position.trim() || form.content.trim().length < 10}>
                    <Send size={16} />
                    {saving ? '发布中...' : '发布'}
                  </Button>
                  <Button type="button" variant="secondary" onClick={() => setShowForm(false)}>
                    取消
                  </Button>
                </div>
              </form>
            ) : selected ? (
              <div className="space-y-5">
                <div>
                  <div className="mb-2 flex flex-wrap items-center gap-2">
                    <Badge tone={resultTone(selected.result)}>{resultLabel[selected.result]}</Badge>
                    <Badge tone={difficultyTone(selected.difficulty)}>{difficultyLabel[selected.difficulty]}</Badge>
                    <Badge tone="neutral">{visibilityLabel[selected.visibility]}</Badge>
                    {selected.allow_profile_usage && selected.visibility !== 'private' && <Badge tone="info">可用于公司面试参考</Badge>}
                  </div>
                  <h2 className="text-lg font-bold leading-7 text-slate-950">{selected.company} · {selected.position}</h2>
                  <p className="mt-2 text-sm leading-6 text-slate-500">
                    {selected.author_label} · {selected.city || '城市未知'} · {selected.interview_date || '日期未知'}
                  </p>
                </div>

                <div className="grid grid-cols-2 gap-3 text-sm">
                  <div className="rounded-md bg-slate-50 px-3 py-3">
                    <div className="text-xs text-slate-500">轮次</div>
                    <div className="mt-1 font-semibold text-slate-900">{selected.rounds || '-'}</div>
                  </div>
                  <div className="rounded-md bg-slate-50 px-3 py-3">
                    <div className="text-xs text-slate-500">互动</div>
                    <div className="mt-1 font-semibold text-slate-900">{selected.view_count} 浏览 / {selected.like_count} 赞</div>
                  </div>
                </div>

                {selected.tags.length > 0 && (
                  <div className="flex flex-wrap gap-2">
                    {selected.tags.map((item) => <Badge key={item} tone="info">{item}</Badge>)}
                  </div>
                )}

                {selected.questions.length > 0 && (
                  <div>
                    <h3 className="mb-2 text-sm font-semibold text-slate-900">被问到的问题</h3>
                    <div className="space-y-2">
                      {selected.questions.map((item) => (
                        <div key={item} className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm leading-6 text-slate-700">
                          {item}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {selected.process && (
                  <div>
                    <h3 className="mb-2 text-sm font-semibold text-slate-900">流程记录</h3>
                    <p className="whitespace-pre-wrap rounded-md bg-slate-50 px-3 py-3 text-sm leading-6 text-slate-700">{selected.process}</p>
                  </div>
                )}

                <div>
                  <h3 className="mb-2 text-sm font-semibold text-slate-900">复盘正文</h3>
                  <p className="whitespace-pre-wrap text-sm leading-7 text-slate-700">{selected.content}</p>
                </div>

                <div className="flex flex-wrap gap-2">
                  <Button type="button" variant="secondary" onClick={likeSelected}>
                    <Heart size={16} />
                    赞同
                  </Button>
                  {selected.can_edit && (
                    <Button type="button" variant="danger" onClick={deleteSelected}>
                      <Trash2 size={16} />
                      删除
                    </Button>
                  )}
                </div>
              </div>
            ) : (
              <EmptyState title="选择一条面经" action={<Button type="button" onClick={() => setShowForm(true)}>发布面经</Button>} />
            )}
          </Card>
        </div>
      </div>
    </AppShell>
  )
}
