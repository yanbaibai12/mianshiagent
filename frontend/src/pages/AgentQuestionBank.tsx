import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router'
import { BookOpenCheck, CheckCircle2, ChevronLeft, ChevronRight, Eye, EyeOff, Search, Star, Target, XCircle } from 'lucide-react'
import AppShell from '../components/AppShell'
import { Badge, Button, EmptyState, Field, LoadingState, ProgressBar } from '../components/ui'
import { communityApi, type AgentQuestionBankItem, type AgentQuestionBankList, type AgentQuestionPracticeState, type TrainingProfile } from '../services/community'

const difficultyLabel: Record<string, string> = {
  basic: '基础',
  intermediate: '进阶',
  advanced: '高阶',
  easy: '基础',
  medium: '中等',
  hard: '高阶',
}

function difficultyTone(value: string): 'neutral' | 'success' | 'warning' | 'danger' | 'info' {
  if (value === 'easy') return 'success'
  if (value === 'medium') return 'warning'
  if (value === 'hard') return 'danger'
  if (value === 'basic') return 'success'
  if (value === 'intermediate') return 'warning'
  if (value === 'advanced') return 'danger'
  return 'neutral'
}

function shortText(value: string, maxLength = 120) {
  const text = value.trim()
  return text.length > maxLength ? `${text.slice(0, maxLength)}...` : text
}

function statusLabel(status?: string) {
  if (status === 'known') return '我会了'
  if (status === 'unknown') return '不会'
  if (status === 'review') return '待复习'
  return '未练'
}

export default function AgentQuestionBankPage() {
  const navigate = useNavigate()
  const [payload, setPayload] = useState<AgentQuestionBankList | null>(null)
  const [profile, setProfile] = useState<TrainingProfile | null>(null)
  const [selected, setSelected] = useState<AgentQuestionBankItem | null>(null)
  const [query, setQuery] = useState('')
  const [section, setSection] = useState('')
  const [difficulty, setDifficulty] = useState('')
  const [role, setRole] = useState('')
  const [skill, setSkill] = useState('')
  const [practiceFilter, setPracticeFilter] = useState<'favorite' | 'wrong' | 'due' | 'unseen' | ''>('')
  const [visibleAnswers, setVisibleAnswers] = useState<Record<string, boolean>>({})
  const [offset, setOffset] = useState(0)
  const [mobileView, setMobileView] = useState<'filters' | 'question' | 'list'>('question')
  const [loading, setLoading] = useState(true)
  const [updating, setUpdating] = useState('')
  const [error, setError] = useState('')

  const limit = 20

  const loadQuestions = async () => {
    setError('')
    const res = await communityApi.listAgentQuestions({
      q: query.trim() || undefined,
      section: section || undefined,
      difficulty: difficulty || undefined,
      role: role || undefined,
      skill: skill || undefined,
      practice_filter: practiceFilter || undefined,
      limit,
      offset,
    })
    setPayload(res.data)
    setSelected((current) => {
      if (current && res.data.items.some((item) => item.id === current.id)) return current
      return res.data.items[0] || null
    })
  }

  const loadProfile = async () => {
    const res = await communityApi.trainingProfile()
    setProfile(res.data)
  }

  useEffect(() => {
    setLoading(true)
    Promise.all([loadQuestions(), loadProfile()])
      .catch((err: any) => setError(err.response?.data?.detail || 'Agent 八股题加载失败'))
      .finally(() => setLoading(false))
  }, [query, section, difficulty, role, skill, practiceFilter, offset])

  const filters = payload?.filters
  const activeFilterCount = useMemo(
    () => [query.trim(), section, difficulty, role, skill, practiceFilter].filter(Boolean).length,
    [query, section, difficulty, role, skill, practiceFilter],
  )

  const resetFilters = () => {
    setQuery('')
    setSection('')
    setDifficulty('')
    setRole('')
    setSkill('')
    setPracticeFilter('')
    setOffset(0)
  }

  const mergePracticeState = (questionId: string, state: AgentQuestionPracticeState) => {
    setPayload((current) => current
      ? {
        ...current,
        items: current.items.map((item) => item.id === questionId ? { ...item, practice_state: state } : item),
      }
      : current)
    setSelected((current) => current && current.id === questionId ? { ...current, practice_state: state } : current)
  }

  const updatePractice = async (questionId: string, payload: Parameters<typeof communityApi.updateAgentQuestionPractice>[1]) => {
    setUpdating(questionId)
    setError('')
    try {
      const res = await communityApi.updateAgentQuestionPractice(questionId, payload)
      mergePracticeState(questionId, res.data)
      await loadProfile()
    } catch (err: any) {
      setError(err.response?.data?.detail || '练习状态更新失败')
    } finally {
      setUpdating('')
    }
  }

  if (loading && !payload) return <LoadingState label="正在加载 Agent 八股题库" />

  return (
    <AppShell
      title="Agent 八股题"
      description="按主题练习高频问题，记录掌握情况并安排下一次复习。"
      contentWidth="wide"
      actions={
        <>
          <Button type="button" variant="secondary" onClick={() => navigate('/experiences')}>真实面经</Button>
          <Button type="button" onClick={() => navigate('/interviews/new')}>开始模拟面试</Button>
        </>
      }
    >
      <div className="space-y-5">
        {error && <div className="rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div>}

        <div className="metric-strip" aria-label="题库练习概览">
          <div className="metric-strip-item"><div className="metric-strip-label">题库</div><div className="metric-strip-value">{payload?.total ?? '-'}</div></div>
          <div className="metric-strip-item"><div className="metric-strip-label">已练</div><div className="metric-strip-value">{profile?.stats.practice_count ?? 0}</div></div>
          <div className="metric-strip-item"><div className="metric-strip-label">错题</div><div className="metric-strip-value">{profile?.stats.wrong_count ?? 0}</div></div>
          <div className="metric-strip-item"><div className="metric-strip-label">今日待复习</div><div className="metric-strip-value">{profile?.stats.due_count ?? 0}</div></div>
        </div>

        <div className="sticky top-16 z-20 grid grid-cols-3 rounded-lg border border-slate-200 bg-white p-1 shadow-sm xl:hidden" aria-label="题库移动视图">
          {[
            { key: 'question', label: '当前题' },
            { key: 'list', label: '题单' },
            { key: 'filters', label: '筛选' },
          ].map((item) => (
            <button
              key={item.key}
              type="button"
              className={`rounded-md px-3 py-2 text-sm font-semibold ${mobileView === item.key ? 'bg-slate-900 text-white' : 'text-slate-500'}`}
              onClick={() => setMobileView(item.key as typeof mobileView)}
            >
              {item.label}
            </button>
          ))}
        </div>

        <div className="grid grid-cols-1 items-start gap-4 xl:grid-cols-[220px_390px_minmax(0,1fr)]">
          <aside className={`workspace-panel order-1 xl:sticky xl:top-8 xl:block xl:max-h-[calc(100vh-4rem)] xl:overflow-y-auto ${mobileView === 'filters' ? 'block' : 'hidden'}`}>
            <div className="workspace-panel-header flex items-center justify-between gap-2">
              <div>
                <h2 className="font-semibold text-slate-950">练习范围</h2>
                <p className="mt-0.5 text-xs text-slate-500">{activeFilterCount ? `${activeFilterCount} 项筛选` : '全部题目'}</p>
              </div>
              {activeFilterCount > 0 && <button type="button" onClick={resetFilters} className="text-xs font-semibold text-slate-500 hover:text-slate-950">重置</button>}
            </div>
            <div className="workspace-panel-body space-y-5">
              <div className="space-y-1">
                {[
                  { key: '', label: '全部题目', count: payload?.total ?? 0 },
                  { key: 'due', label: '待复习', count: profile?.stats.due_count ?? 0 },
                  { key: 'wrong', label: '错题本', count: profile?.stats.wrong_count ?? 0 },
                  { key: 'favorite', label: '收藏', count: profile?.stats.favorite_count ?? 0 },
                  { key: 'unseen', label: '未练习', count: null },
                ].map((item) => (
                  <button
                    key={item.key || 'all'}
                    type="button"
                    className={`flex w-full items-center justify-between rounded-md px-3 py-2 text-left text-sm font-medium ${practiceFilter === item.key ? 'bg-slate-900 text-white' : 'text-slate-600 hover:bg-slate-100 hover:text-slate-950'}`}
                    onClick={() => { setPracticeFilter(item.key as typeof practiceFilter); setOffset(0) }}
                  >
                    <span>{item.label}</span>
                    {item.count !== null && <span className={practiceFilter === item.key ? 'text-slate-300' : 'text-slate-400'}>{item.count}</span>}
                  </button>
                ))}
              </div>

              <div className="border-t border-slate-200 pt-4">
                <Field label="关键词">
                  <div className="relative">
                    <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                    <input className="input pl-9" value={query} onChange={(event) => { setQuery(event.target.value); setOffset(0) }} placeholder="搜索题目" />
                  </div>
                </Field>
              </div>
              <Field label="方向"><select className="select" value={section} onChange={(event) => { setSection(event.target.value); setOffset(0) }}><option value="">全部方向</option>{filters?.sections.map((item) => <option key={item} value={item}>{item}</option>)}</select></Field>
              <Field label="难度"><select className="select" value={difficulty} onChange={(event) => { setDifficulty(event.target.value); setOffset(0) }}><option value="">全部难度</option>{filters?.difficulties.map((item) => <option key={item} value={item}>{difficultyLabel[item] || item}</option>)}</select></Field>
              <Field label="角色"><select className="select" value={role} onChange={(event) => { setRole(event.target.value); setOffset(0) }}><option value="">全部角色</option>{filters?.roles.map((item) => <option key={item} value={item}>{item}</option>)}</select></Field>
              <Field label="技能"><select className="select" value={skill} onChange={(event) => { setSkill(event.target.value); setOffset(0) }}><option value="">全部技能</option>{filters?.skills.map((item) => <option key={item} value={item}>{item}</option>)}</select></Field>

              <div className="border-t border-slate-200 pt-4">
                <div className="mb-3 text-xs font-semibold text-slate-500">掌握情况</div>
                <div className="space-y-3">
                  {profile?.dimensions.map((dimension) => (
                    <div key={dimension.dimension_key}>
                      <div className="mb-1.5 flex items-center justify-between gap-2 text-xs"><span className="truncate font-medium text-slate-700">{dimension.dimension_label}</span><span className="font-semibold text-slate-500">{dimension.mastery_score}</span></div>
                      <ProgressBar value={dimension.mastery_score} />
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </aside>

          <section className={`workspace-panel order-3 min-w-0 xl:order-2 xl:block xl:max-h-[calc(100vh-4rem)] xl:overflow-y-auto ${mobileView === 'list' ? 'block' : 'hidden'}`}>
            <div className="workspace-panel-header sticky top-0 z-10 flex items-center justify-between gap-3 bg-white">
              <div><h2 className="font-semibold text-slate-950">题目</h2><p className="mt-0.5 text-xs text-slate-500">{payload?.total || 0} 道结果</p></div>
              <div className="flex items-center gap-1">
                <Button type="button" size="sm" variant="ghost" title="上一页" aria-label="上一页" onClick={() => setOffset(Math.max(0, offset - limit))} disabled={offset === 0}><ChevronLeft size={16} /></Button>
                <span className="min-w-12 text-center text-xs text-slate-500">{Math.floor(offset / limit) + 1}</span>
                <Button type="button" size="sm" variant="ghost" title="下一页" aria-label="下一页" onClick={() => setOffset(offset + limit)} disabled={!payload || offset + limit >= payload.total}><ChevronRight size={16} /></Button>
              </div>
            </div>
            <div>
              {payload?.items.map((item) => (
                <button
                  type="button"
                  key={item.id}
                  className={`block w-full border-b border-slate-200 px-4 py-4 text-left transition last:border-b-0 ${selected?.id === item.id ? 'bg-slate-100 shadow-[inset_3px_0_0_#a4473d]' : 'bg-white hover:bg-slate-50'}`}
                  onClick={() => {
                    setSelected(item)
                    setMobileView('question')
                    window.scrollTo({ top: 0, behavior: 'smooth' })
                  }}
                >
                  <div className="mb-2 flex items-center justify-between gap-3 text-xs">
                    <div className="flex min-w-0 items-center gap-2"><span className="truncate text-slate-500">{item.section}</span><span className="text-slate-300">/</span><span className="shrink-0 font-medium text-slate-600">{difficultyLabel[item.difficulty] || item.difficulty}</span></div>
                    <div className="flex shrink-0 items-center gap-1.5">
                      {item.practice_state?.is_favorite && <Star size={13} className="fill-amber-400 text-amber-500" />}
                      {item.practice_state?.is_wrong && <XCircle size={13} className="text-rose-600" />}
                      <span className="text-slate-500">{statusLabel(item.practice_state?.mastery_status)}</span>
                    </div>
                  </div>
                  <div className="text-sm font-semibold leading-6 text-slate-950">{item.question}</div>
                  <p className="mt-1.5 text-xs leading-5 text-slate-500">{shortText(item.focus, 72)}</p>
                </button>
              ))}
              {payload?.items.length === 0 && <EmptyState title="没有匹配题卡" description="换一个关键词或清空筛选后再查看。" />}
            </div>
          </section>

          <section className={`workspace-panel order-2 min-w-0 xl:order-3 xl:sticky xl:top-8 xl:block xl:max-h-[calc(100vh-4rem)] xl:overflow-y-auto ${mobileView === 'question' ? 'block' : 'hidden'}`}>
            {selected ? (
              <div>
                <div className="border-b border-slate-200 p-5">
                  <div className="mb-3 flex flex-wrap items-center gap-2">
                    <Badge tone={difficultyTone(selected.difficulty)}>{difficultyLabel[selected.difficulty] || selected.difficulty}</Badge>
                    <span className="text-xs text-slate-500">{selected.section}</span>
                    <span className="text-xs text-slate-400">{selected.source_title} · {selected.source_version}</span>
                  </div>
                  <h2 className="text-xl font-bold leading-8 text-slate-950">{selected.question}</h2>
                  <p className="mt-3 text-sm leading-6 text-slate-600">{selected.focus}</p>
                </div>

                <div className="border-b border-slate-200 bg-slate-50 p-4">
                  <div className="grid grid-cols-2 gap-2 sm:grid-cols-[1fr_1fr_auto_auto]">
                    <Button type="button" variant="success" disabled={updating === selected.id} onClick={() => updatePractice(selected.id, { mastery_status: 'known' })}><CheckCircle2 size={16} />我会了</Button>
                    <Button type="button" variant="danger" disabled={updating === selected.id} onClick={() => updatePractice(selected.id, { mastery_status: 'unknown', is_wrong: true })}><XCircle size={16} />不会</Button>
                    <Button type="button" variant="secondary" title={selected.practice_state?.is_favorite ? '取消收藏' : '收藏'} aria-label={selected.practice_state?.is_favorite ? '取消收藏' : '收藏'} disabled={updating === selected.id} onClick={() => updatePractice(selected.id, { is_favorite: !selected.practice_state?.is_favorite })}><Star size={16} className={selected.practice_state?.is_favorite ? 'fill-amber-400 text-amber-500' : ''} /></Button>
                    <Button type="button" variant="secondary" title={selected.practice_state?.is_wrong ? '移出错题' : '加入错题'} aria-label={selected.practice_state?.is_wrong ? '移出错题' : '加入错题'} disabled={updating === selected.id} onClick={() => updatePractice(selected.id, { is_wrong: !selected.practice_state?.is_wrong })}><XCircle size={16} className={selected.practice_state?.is_wrong ? 'text-rose-600' : ''} /></Button>
                  </div>
                  <Button type="button" className="mt-2 w-full" variant="secondary" onClick={() => setVisibleAnswers({ ...visibleAnswers, [selected.id]: !visibleAnswers[selected.id] })}>{visibleAnswers[selected.id] ? <EyeOff size={16} /> : <Eye size={16} />}{visibleAnswers[selected.id] ? '隐藏答案' : '显示答案'}</Button>
                </div>

                <div className="space-y-6 p-5">
                  <Field label="下一次复习">
                    <input className="input" type="date" value={selected.practice_state?.next_review_at ? selected.practice_state.next_review_at.slice(0, 10) : ''} onChange={(event) => { const value = event.target.value; updatePractice(selected.id, { next_review_at: value ? new Date(`${value}T09:00:00`).toISOString() : null }) }} />
                  </Field>

                  <section>
                    <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-slate-950"><BookOpenCheck size={16} />精简答案</div>
                  {visibleAnswers[selected.id] ? (
                      <p className="border-l-2 border-emerald-700 pl-4 text-sm leading-7 text-slate-800">{selected.concise_answer}</p>
                  ) : (
                      <div className="rounded-md bg-slate-50 px-4 py-5 text-center text-sm text-slate-500">先尝试口述答案，再点击“显示答案”。</div>
                  )}
                  </section>

                  <section className="border-t border-slate-200 pt-5">
                    <h3 className="mb-3 text-sm font-semibold text-slate-950">参考答题要点</h3>
                  {visibleAnswers[selected.id] ? (
                      <ol className="space-y-3 text-sm leading-6 text-slate-700">
                        {selected.answer_points.map((item, index) => <li key={item} className="flex gap-3"><span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-slate-100 text-[11px] font-bold text-slate-600">{index + 1}</span><span>{item}</span></li>)}
                      </ol>
                    ) : <p className="text-sm text-slate-500">显示答案后查看结构化要点。</p>}
                  </section>

                  <section className="border-t border-slate-200 pt-5">
                    <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-950"><Target size={15} />面试官可能追问</div>
                    <div className="space-y-2">
                      {selected.followups.map((item) => <div key={item} className="rounded-md border border-slate-200 px-3 py-2.5 text-sm leading-6 text-slate-700">{item}</div>)}
                    </div>
                  </section>

                  <section className="border-t border-slate-200 pt-5">
                    <h3 className="mb-3 text-sm font-semibold text-slate-950">容易失分的回答</h3>
                    <ul className="space-y-2 text-sm leading-6 text-rose-700">
                      {selected.red_flags.map((item) => <li key={item} className="flex gap-2"><XCircle size={15} className="mt-1 shrink-0" /><span>{item}</span></li>)}
                    </ul>
                  </section>
                </div>
              </div>
            ) : (
              <div className="p-5"><EmptyState title="请选择一道题" /></div>
            )}
          </section>
        </div>
      </div>
    </AppShell>
  )
}
