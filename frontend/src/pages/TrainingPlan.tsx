import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router'
import {
  BookOpenCheck,
  CalendarDays,
  Check,
  ChevronRight,
  Clock3,
  FileSearch,
  FolderSearch2,
  MessageSquareText,
  RefreshCw,
  SkipForward,
  Target,
} from 'lucide-react'
import AppShell from '../components/AppShell'
import { Badge, Button, Card, EmptyState, LoadingState, ProgressBar } from '../components/ui'
import {
  TrainingPlan,
  TrainingPlanTask,
  TrainingTaskStatus,
  trainingPlanApi,
} from '../services/trainingPlans'

const taskTypeLabels: Record<string, string> = {
  agent_question: '题卡练习',
  wrong_review: '错题复习',
  mock_interview: '模拟面试',
  experience_reading: '面经阅读',
  project_review: '项目复盘',
}

const dimensionLabels: Record<string, string> = {
  rag: 'RAG',
  tool_calling: 'Tool Calling',
  agent_memory: 'Agent Memory',
  prompt_injection: 'Prompt Injection',
  engineering: '工程化',
}

function localDateString(value = new Date()) {
  const offset = value.getTimezoneOffset() * 60_000
  return new Date(value.getTime() - offset).toISOString().slice(0, 10)
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    month: 'numeric',
    day: 'numeric',
    weekday: 'short',
  }).format(new Date(`${value}T00:00:00`))
}

function taskIcon(taskType: string) {
  if (taskType === 'mock_interview') return <MessageSquareText size={17} />
  if (taskType === 'experience_reading') return <FileSearch size={17} />
  if (taskType === 'project_review') return <FolderSearch2 size={17} />
  return <BookOpenCheck size={17} />
}

function statusTone(status: TrainingTaskStatus): 'neutral' | 'success' | 'warning' {
  if (status === 'completed') return 'success'
  if (status === 'skipped') return 'neutral'
  return 'warning'
}

function statusLabel(status: TrainingTaskStatus) {
  if (status === 'completed') return '已完成'
  if (status === 'skipped') return '已跳过'
  return '待完成'
}

function TaskRow({
  task,
  weekStart,
  weekEnd,
  busyTaskId,
  onUpdate,
  onOpen,
}: {
  task: TrainingPlanTask
  weekStart: string
  weekEnd: string
  busyTaskId: string
  onUpdate: (task: TrainingPlanTask, update: { status?: TrainingTaskStatus; scheduled_date?: string }) => void
  onOpen: (task: TrainingPlanTask) => void
}) {
  const disabled = busyTaskId === task.id
  return (
    <div className="-mx-2 border-b border-slate-100 px-2 py-4 transition last:border-b-0 hover:bg-slate-50/80">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="flex h-8 w-8 items-center justify-center rounded-md bg-slate-100 text-slate-700">{taskIcon(task.task_type)}</span>
            <Badge tone={statusTone(task.status)}>{statusLabel(task.status)}</Badge>
            <Badge>{taskTypeLabels[task.task_type] || task.task_type}</Badge>
            <span className="inline-flex items-center gap-1 text-xs text-slate-500">
              <Clock3 size={13} />
              {task.estimated_minutes} 分钟
            </span>
          </div>
          <h3 className="mt-2 break-words text-sm font-semibold leading-6 text-slate-950">{task.title}</h3>
          <p className="mt-1 text-sm leading-6 text-slate-600">{task.description}</p>
          <p className="mt-2 text-xs leading-5 text-slate-500">推荐原因：{task.recommendation_reason}</p>
          {task.target_dimensions.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-2">
              {task.target_dimensions.map((dimension) => (
                <Badge key={dimension} tone="info">{dimensionLabels[dimension] || dimension}</Badge>
              ))}
            </div>
          )}
        </div>
        <div className="flex w-full flex-col gap-2 lg:w-auto lg:min-w-52">
          <label className="flex items-center gap-2 text-xs font-medium text-slate-600">
            <CalendarDays size={15} />
            <input
              aria-label={`调整${task.title}日期`}
              type="date"
              className="input min-w-0 flex-1 py-1.5"
              min={weekStart}
              max={weekEnd}
              value={task.scheduled_date}
              disabled={disabled}
              onChange={(event) => onUpdate(task, { scheduled_date: event.target.value })}
            />
          </label>
          <div className="flex flex-wrap gap-2 lg:justify-end">
            {(task.related_question_id || task.related_interview_id || task.related_experience_id) && (
              <Button type="button" size="sm" variant="ghost" onClick={() => onOpen(task)}>
                开始
                <ChevronRight size={15} />
              </Button>
            )}
            {task.status !== 'completed' && (
              <Button type="button" size="sm" variant="success" disabled={disabled} onClick={() => onUpdate(task, { status: 'completed' })}>
                <Check size={15} />
                完成
              </Button>
            )}
            {task.status === 'pending' && (
              <Button type="button" size="sm" variant="ghost" disabled={disabled} onClick={() => onUpdate(task, { status: 'skipped' })}>
                <SkipForward size={15} />
                跳过
              </Button>
            )}
            {task.status !== 'pending' && (
              <Button type="button" size="sm" variant="ghost" disabled={disabled} onClick={() => onUpdate(task, { status: 'pending' })}>
                恢复
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

export default function TrainingPlanPage() {
  const navigate = useNavigate()
  const [plan, setPlan] = useState<TrainingPlan | null>(null)
  const [loading, setLoading] = useState(true)
  const [working, setWorking] = useState(false)
  const [busyTaskId, setBusyTaskId] = useState('')
  const [error, setError] = useState('')
  const today = localDateString()

  useEffect(() => {
    trainingPlanApi.current()
      .then((response) => setPlan(response.data))
      .catch((err: any) => {
        if (err.response?.status !== 404) setError(err.response?.data?.detail || '训练计划加载失败')
      })
      .finally(() => setLoading(false))
  }, [])

  const groupedTasks = useMemo(() => {
    const sorted = [...(plan?.tasks || [])].sort((a, b) =>
      a.scheduled_date.localeCompare(b.scheduled_date) || b.priority - a.priority,
    )
    return {
      today: sorted.filter((task) => task.scheduled_date === today),
      upcoming: sorted.filter((task) => task.scheduled_date !== today),
    }
  }, [plan, today])

  const generate = async () => {
    setWorking(true)
    setError('')
    try {
      const response = await trainingPlanApi.generate()
      setPlan(response.data)
    } catch (err: any) {
      setError(err.response?.data?.detail || '训练计划生成失败')
    } finally {
      setWorking(false)
    }
  }

  const regenerate = async () => {
    if (!plan) return
    setWorking(true)
    setError('')
    try {
      const response = await trainingPlanApi.regenerate(plan.id)
      setPlan(response.data)
    } catch (err: any) {
      setError(err.response?.data?.detail || '训练计划重新生成失败')
    } finally {
      setWorking(false)
    }
  }

  const updateTask = async (
    task: TrainingPlanTask,
    update: { status?: TrainingTaskStatus; scheduled_date?: string },
  ) => {
    if (!plan) return
    setBusyTaskId(task.id)
    setError('')
    try {
      const response = await trainingPlanApi.updateTask(plan.id, task.id, update)
      setPlan(response.data)
    } catch (err: any) {
      setError(err.response?.data?.detail || '训练任务更新失败')
    } finally {
      setBusyTaskId('')
    }
  }

  const openTask = (task: TrainingPlanTask) => {
    if (task.related_question_id) navigate(`/agent-questions?question=${encodeURIComponent(task.related_question_id)}`)
    else if (task.related_interview_id) navigate(`/interviews/${task.related_interview_id}`)
    else if (task.related_experience_id) navigate(`/experiences?experience=${task.related_experience_id}`)
  }

  if (loading) return <LoadingState label="正在加载本周训练计划" />

  return (
    <AppShell
      title="本周训练计划"
      description="把错题、弱项、项目和目标公司信息排成每天可执行的训练任务。"
      actions={plan ? (
        <Button type="button" variant="secondary" disabled={working} onClick={regenerate}>
          <RefreshCw size={16} />
          {working ? '生成中...' : '重新生成'}
        </Button>
      ) : undefined}
    >
      <div className="space-y-6" data-testid="training-plan-page">
        {error && <div className="rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div>}
        {!plan ? (
          <EmptyState
            title="本周还没有训练计划"
            description="根据已有错题、复习记录和最近面试安排 7 天任务。"
            action={<Button type="button" disabled={working} onClick={generate}>{working ? '生成中...' : '生成本周计划'}</Button>}
          />
        ) : (
          <>
            <Card>
              <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone={plan.status === 'completed' ? 'success' : 'info'}>{plan.status === 'completed' ? '本周已完成' : '进行中'}</Badge>
                    <span className="text-sm text-slate-500">{formatDate(plan.week_start)} 至 {formatDate(plan.week_end)}</span>
                  </div>
                  <p className="mt-3 max-w-3xl text-sm leading-7 text-slate-700">{plan.plan_summary}</p>
                  <div className="mt-4 max-w-xl">
                    <div className="mb-2 flex items-center justify-between text-sm">
                      <span className="font-semibold text-slate-700">完成进度</span>
                      <span className="text-slate-500">{plan.completion_rate}%</span>
                    </div>
                    <ProgressBar value={plan.completion_rate} />
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-6 border-t border-slate-200 pt-4 lg:w-72 lg:border-l lg:border-t-0 lg:pl-6 lg:pt-0">
                  <div>
                    <div className="flex items-center gap-2 text-xs font-semibold text-slate-500"><CalendarDays size={15} /> 本周任务</div>
                    <div className="mt-2 text-2xl font-bold text-slate-950">{plan.tasks.length}</div>
                    <div className="mt-1 text-xs text-slate-500">条训练动作</div>
                  </div>
                  <div>
                    <div className="flex items-center gap-2 text-xs font-semibold text-slate-500"><Clock3 size={15} /> 预计用时</div>
                    <div className="mt-2 text-2xl font-bold text-slate-950">{plan.estimated_minutes}</div>
                    <div className="mt-1 text-xs text-slate-500">分钟</div>
                  </div>
                </div>
              </div>
            </Card>

            {Boolean(plan.generation_metadata.weak_dimensions?.length) && (
              <Card>
                <div className="mb-4 flex items-center gap-2">
                  <Target size={18} className="text-slate-600" />
                  <div>
                    <h2 className="card-title">弱项提升目标</h2>
                    <p className="card-subtitle">完成记录会用于调整下一次的练习内容。</p>
                  </div>
                </div>
                <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                  {plan.generation_metadata.weak_dimensions?.map((dimension) => (
                    <div key={dimension.dimension_key} className="border-l-2 border-slate-400 pl-3">
                      <div className="flex items-center justify-between gap-3 text-sm">
                        <span className="font-semibold text-slate-900">{dimension.dimension_label}</span>
                        <span className="text-slate-500">掌握度 {dimension.mastery_score}</span>
                      </div>
                      <div className="mt-2"><ProgressBar value={dimension.mastery_score} /></div>
                    </div>
                  ))}
                </div>
              </Card>
            )}

            <Card>
              <div className="mb-2">
                <h2 className="card-title">今日任务</h2>
                <p className="card-subtitle">{formatDate(today)}，单日总时长不超过 45 分钟。</p>
              </div>
              {groupedTasks.today.length ? groupedTasks.today.map((task) => (
                <TaskRow key={task.id} task={task} weekStart={plan.week_start} weekEnd={plan.week_end} busyTaskId={busyTaskId} onUpdate={updateTask} onOpen={openTask} />
              )) : <div className="py-6 text-sm text-slate-500">今日没有安排任务，可从后续任务中调整一项到今天。</div>}
            </Card>

            <Card>
              <div className="mb-2">
                <h2 className="card-title">后续任务</h2>
                <p className="card-subtitle">覆盖推荐题卡、错题复习、模拟面试、面经阅读和项目复盘。</p>
              </div>
              {groupedTasks.upcoming.map((task) => (
                <TaskRow key={task.id} task={task} weekStart={plan.week_start} weekEnd={plan.week_end} busyTaskId={busyTaskId} onUpdate={updateTask} onOpen={openTask} />
              ))}
            </Card>
          </>
        )}
      </div>
    </AppShell>
  )
}
