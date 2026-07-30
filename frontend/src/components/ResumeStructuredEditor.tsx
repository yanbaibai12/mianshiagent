import { Plus, Trash2 } from 'lucide-react'
import type { ReactNode } from 'react'
import { Badge, Button, EmptyState, Field } from './ui'

export type ResumeData = {
  personal?: Record<string, unknown>
  education?: Array<Record<string, unknown>>
  experience?: Array<Record<string, unknown>>
  projects?: Array<Record<string, unknown>>
  skills?: string[]
  summary?: string
  [key: string]: unknown
}

type SectionKey = 'education' | 'experience' | 'projects'

const sectionTitles: Record<SectionKey, string> = {
  education: '教育背景',
  experience: '工作/实习经历',
  projects: '项目经历',
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? { ...value } as Record<string, unknown> : {}
}

function asRecordArray(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value) ? value.map(asRecord) : []
}

function asString(value: unknown): string {
  return typeof value === 'string' ? value : value === null || value === undefined ? '' : String(value)
}

function asStringArray(value: unknown): string[] {
  if (Array.isArray(value)) return value.map(asString).filter(Boolean)
  if (typeof value === 'string') return value.split(/[\n,，、;；]+/).map((item) => item.trim()).filter(Boolean)
  return []
}

function splitLines(value: string): string[] {
  return value.split(/\n+/).map((item) => item.trim()).filter(Boolean)
}

function joinList(value: unknown): string {
  return asStringArray(value).join('\n')
}

export function normalizeResumeData(value: unknown): ResumeData {
  const base = asRecord(value)
  return {
    ...base,
    personal: asRecord(base.personal),
    education: asRecordArray(base.education),
    experience: asRecordArray(base.experience),
    projects: asRecordArray(base.projects),
    skills: asStringArray(base.skills),
    summary: asString(base.summary),
  }
}

function compactLine(parts: string[]) {
  return parts.filter(Boolean).join(' · ')
}

function updateRecordList(
  data: ResumeData,
  section: SectionKey,
  index: number,
  nextItem: Record<string, unknown>,
) {
  const items = asRecordArray(data[section])
  items[index] = nextItem
  return { ...data, [section]: items }
}

function removeRecordListItem(data: ResumeData, section: SectionKey, index: number) {
  const items = asRecordArray(data[section])
  return { ...data, [section]: items.filter((_, itemIndex) => itemIndex !== index) }
}

function addRecordListItem(data: ResumeData, section: SectionKey, item: Record<string, unknown>) {
  return { ...data, [section]: [...asRecordArray(data[section]), item] }
}

function updatePoint(
  data: ResumeData,
  section: 'experience' | 'projects',
  itemIndex: number,
  pointIndex: number,
  field: 'title' | 'description',
  value: string,
) {
  const items = asRecordArray(data[section])
  const item = asRecord(items[itemIndex])
  const points = asRecordArray(item.interview_points)
  points[pointIndex] = { ...asRecord(points[pointIndex]), [field]: value }
  item.interview_points = points
  items[itemIndex] = item
  return { ...data, [section]: items }
}

function addPoint(data: ResumeData, section: 'experience' | 'projects', itemIndex: number) {
  const items = asRecordArray(data[section])
  const item = asRecord(items[itemIndex])
  item.interview_points = [
    ...asRecordArray(item.interview_points),
    { id: `p-${Date.now()}`, title: '', description: '' },
  ]
  items[itemIndex] = item
  return { ...data, [section]: items }
}

function removePoint(data: ResumeData, section: 'experience' | 'projects', itemIndex: number, pointIndex: number) {
  const items = asRecordArray(data[section])
  const item = asRecord(items[itemIndex])
  item.interview_points = asRecordArray(item.interview_points).filter((_, index) => index !== pointIndex)
  items[itemIndex] = item
  return { ...data, [section]: items }
}

export function ResumeStructuredEditor({
  value,
  onChange,
}: {
  value: ResumeData
  onChange: (nextValue: ResumeData) => void
}) {
  const data = normalizeResumeData(value)
  const personal = asRecord(data.personal)

  const updatePersonal = (field: string, nextValue: string) => {
    onChange({ ...data, personal: { ...personal, [field]: nextValue } })
  }

  const updateItemField = (section: SectionKey, index: number, field: string, nextValue: unknown) => {
    const item = { ...asRecord(asRecordArray(data[section])[index]), [field]: nextValue }
    onChange(updateRecordList(data, section, index, item))
  }

  const addEducation = () => {
    onChange(addRecordListItem(data, 'education', { school: '', major: '', degree: '', time: '' }))
  }

  const addExperience = () => {
    onChange(addRecordListItem(data, 'experience', { company: '', role: '', time: '', highlights: [], interview_points: [] }))
  }

  const addProject = () => {
    onChange(addRecordListItem(data, 'projects', { name: '', role: '', time: '', description: '', tech_stack: [], interview_points: [] }))
  }

  return (
    <div className="space-y-6">
      <section className="rounded-lg border border-slate-200 bg-white p-4">
        <div className="mb-4 flex items-center justify-between gap-3">
          <h3 className="font-semibold text-slate-950">个人信息</h3>
          <Badge tone="neutral">基础</Badge>
        </div>
        <div className="grid gap-4 md:grid-cols-2">
          <Field label="姓名">
            <input className="input" value={asString(personal.name)} onChange={(event) => updatePersonal('name', event.target.value)} />
          </Field>
          <Field label="求职意向">
            <input className="input" value={asString(personal.job_intent)} onChange={(event) => updatePersonal('job_intent', event.target.value)} />
          </Field>
          <Field label="邮箱">
            <input className="input" value={asString(personal.email)} onChange={(event) => updatePersonal('email', event.target.value)} />
          </Field>
          <Field label="电话">
            <input className="input" value={asString(personal.phone)} onChange={(event) => updatePersonal('phone', event.target.value)} />
          </Field>
        </div>
      </section>

      <section className="rounded-lg border border-slate-200 bg-white p-4">
        <div className="mb-4 flex items-center justify-between gap-3">
          <h3 className="font-semibold text-slate-950">{sectionTitles.education}</h3>
          <Button type="button" variant="secondary" size="sm" onClick={addEducation}>
            <Plus size={14} />
            添加
          </Button>
        </div>
        <div className="space-y-4">
          {asRecordArray(data.education).map((item, index) => (
            <div key={index} className="rounded-md border border-slate-200 bg-slate-50 p-3">
              <div className="mb-3 flex items-center justify-between">
                <span className="text-sm font-semibold text-slate-700">教育经历 {index + 1}</span>
                <Button type="button" variant="ghost" size="sm" onClick={() => onChange(removeRecordListItem(data, 'education', index))}>
                  <Trash2 size={14} />
                </Button>
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                <Field label="学校">
                  <input className="input" value={asString(item.school)} onChange={(event) => updateItemField('education', index, 'school', event.target.value)} />
                </Field>
                <Field label="专业">
                  <input className="input" value={asString(item.major)} onChange={(event) => updateItemField('education', index, 'major', event.target.value)} />
                </Field>
                <Field label="学历">
                  <input className="input" value={asString(item.degree)} onChange={(event) => updateItemField('education', index, 'degree', event.target.value)} />
                </Field>
                <Field label="时间">
                  <input className="input" value={asString(item.time)} onChange={(event) => updateItemField('education', index, 'time', event.target.value)} />
                </Field>
              </div>
            </div>
          ))}
          {asRecordArray(data.education).length === 0 && <EmptyState title="暂无教育背景" description="可以手动添加学校、专业、学历和时间。" />}
        </div>
      </section>

      <ExperienceEditor
        title={sectionTitles.experience}
        section="experience"
        items={asRecordArray(data.experience)}
        data={data}
        onChange={onChange}
        onAdd={addExperience}
        updateItemField={updateItemField}
      />

      <ExperienceEditor
        title={sectionTitles.projects}
        section="projects"
        items={asRecordArray(data.projects)}
        data={data}
        onChange={onChange}
        onAdd={addProject}
        updateItemField={updateItemField}
      />

      <section className="rounded-lg border border-slate-200 bg-white p-4">
        <div className="mb-4">
          <h3 className="font-semibold text-slate-950">技能与自我评价</h3>
        </div>
        <div className="grid gap-4 lg:grid-cols-2">
          <Field label="技能关键词" hint="用逗号、顿号或换行分隔">
            <textarea
              className="textarea min-h-40"
              value={asStringArray(data.skills).join('\n')}
              onChange={(event) => onChange({ ...data, skills: asStringArray(event.target.value) })}
            />
          </Field>
          <Field label="自我评价">
            <textarea
              className="textarea min-h-40"
              value={asString(data.summary)}
              onChange={(event) => onChange({ ...data, summary: event.target.value })}
            />
          </Field>
        </div>
      </section>
    </div>
  )
}

function ExperienceEditor({
  title,
  section,
  items,
  data,
  onChange,
  onAdd,
  updateItemField,
}: {
  title: string
  section: 'experience' | 'projects'
  items: Array<Record<string, unknown>>
  data: ResumeData
  onChange: (nextValue: ResumeData) => void
  onAdd: () => void
  updateItemField: (section: SectionKey, index: number, field: string, nextValue: unknown) => void
}) {
  const isProject = section === 'projects'

  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="mb-4 flex items-center justify-between gap-3">
        <h3 className="font-semibold text-slate-950">{title}</h3>
        <Button type="button" variant="secondary" size="sm" onClick={onAdd}>
          <Plus size={14} />
          添加
        </Button>
      </div>
      <div className="space-y-4">
        {items.map((item, index) => (
          <div key={index} className="rounded-md border border-slate-200 bg-slate-50 p-3">
            <div className="mb-3 flex items-center justify-between">
              <span className="text-sm font-semibold text-slate-700">{title} {index + 1}</span>
              <Button type="button" variant="ghost" size="sm" onClick={() => onChange(removeRecordListItem(data, section, index))}>
                <Trash2 size={14} />
              </Button>
            </div>

            <div className="grid gap-3 md:grid-cols-2">
              <Field label={isProject ? '项目名称' : '公司/组织'}>
                <input
                  className="input"
                  value={asString(isProject ? item.name : item.company)}
                  onChange={(event) => updateItemField(section, index, isProject ? 'name' : 'company', event.target.value)}
                />
              </Field>
              <Field label="角色">
                <input className="input" value={asString(item.role)} onChange={(event) => updateItemField(section, index, 'role', event.target.value)} />
              </Field>
              <Field label="时间">
                <input className="input" value={asString(item.time)} onChange={(event) => updateItemField(section, index, 'time', event.target.value)} />
              </Field>
              {isProject && (
                <Field label="技术栈" hint="用逗号、顿号或换行分隔">
                  <input
                    className="input"
                    value={asStringArray(item.tech_stack).join('、')}
                    onChange={(event) => updateItemField(section, index, 'tech_stack', asStringArray(event.target.value))}
                  />
                </Field>
              )}
            </div>

            <div className="mt-3">
              <Field label={isProject ? '项目描述' : '经历亮点'}>
                <textarea
                  className="textarea min-h-32"
                  value={isProject ? asString(item.description) : joinList(item.highlights)}
                  onChange={(event) => updateItemField(section, index, isProject ? 'description' : 'highlights', isProject ? event.target.value : splitLines(event.target.value))}
                />
              </Field>
            </div>

            <div className="mt-4 rounded-md border border-slate-200 bg-white p-3">
              <div className="mb-3 flex items-center justify-between">
                <span className="text-sm font-semibold text-slate-700">可面试要点</span>
                <Button type="button" variant="secondary" size="sm" onClick={() => onChange(addPoint(data, section, index))}>
                  <Plus size={14} />
                  添加要点
                </Button>
              </div>
              <div className="space-y-3">
                {asRecordArray(item.interview_points).map((point, pointIndex) => (
                  <div key={pointIndex} className="grid gap-3 rounded-md bg-slate-50 p-3 md:grid-cols-[1fr_1.4fr_auto]">
                    <input
                      className="input"
                      placeholder="要点标题"
                      value={asString(point.title)}
                      onChange={(event) => onChange(updatePoint(data, section, index, pointIndex, 'title', event.target.value))}
                    />
                    <input
                      className="input"
                      placeholder="要点描述"
                      value={asString(point.description)}
                      onChange={(event) => onChange(updatePoint(data, section, index, pointIndex, 'description', event.target.value))}
                    />
                    <Button type="button" variant="ghost" size="sm" onClick={() => onChange(removePoint(data, section, index, pointIndex))}>
                      <Trash2 size={14} />
                    </Button>
                  </div>
                ))}
                {asRecordArray(item.interview_points).length === 0 && (
                  <p className="text-sm text-slate-500">暂无要点。建议至少补充 1 个面试官可能深挖的技术点、业务难点或成果指标。</p>
                )}
              </div>
            </div>
          </div>
        ))}
        {items.length === 0 && <EmptyState title={`暂无${title}`} description="可以手动添加经历，并补充可面试要点。" />}
      </div>
    </section>
  )
}

export function ResumeStructuredPreview({ value }: { value: ResumeData }) {
  const data = normalizeResumeData(value)
  const personal = asRecord(data.personal)
  const education = asRecordArray(data.education)
  const experience = asRecordArray(data.experience)
  const projects = asRecordArray(data.projects)
  const skills = asStringArray(data.skills)

  return (
    <div className="space-y-6">
      <section className="rounded-lg border border-slate-200 bg-white p-4">
        <div className="mb-3 flex items-center justify-between gap-3">
          <h3 className="font-semibold text-slate-950">{asString(personal.name) || '未命名候选人'}</h3>
          {asString(personal.job_intent) && <Badge tone="info">{asString(personal.job_intent)}</Badge>}
        </div>
        <div className="grid gap-2 text-sm text-slate-600 md:grid-cols-2">
          <div>邮箱：{asString(personal.email) || '-'}</div>
          <div>电话：{asString(personal.phone) || '-'}</div>
        </div>
      </section>

      <PreviewSection title="教育背景" emptyTitle="暂无教育背景">
        {education.map((item, index) => (
          <div key={index} className="rounded-md bg-slate-50 p-3">
            <div className="font-semibold text-slate-900">{asString(item.school) || '未填写学校'}</div>
            <div className="mt-1 text-sm text-slate-500">
              {compactLine([asString(item.major), asString(item.degree), asString(item.time)]) || '-'}
            </div>
          </div>
        ))}
      </PreviewSection>

      <PreviewSection title="工作/实习经历" emptyTitle="暂无工作或实习经历">
        {experience.map((item, index) => (
          <div key={index} className="rounded-md bg-slate-50 p-3">
            <div className="font-semibold text-slate-900">{compactLine([asString(item.company), asString(item.role)]) || '未填写经历'}</div>
            {asString(item.time) && <div className="mt-1 text-sm text-slate-500">{asString(item.time)}</div>}
            <ul className="mt-2 space-y-1 text-sm leading-6 text-slate-600">
              {asStringArray(item.highlights).map((highlight) => <li key={highlight}>- {highlight}</li>)}
            </ul>
            <PointPreview points={asRecordArray(item.interview_points)} />
          </div>
        ))}
      </PreviewSection>

      <PreviewSection title="项目经历" emptyTitle="暂无项目经历">
        {projects.map((item, index) => (
          <div key={index} className="rounded-md bg-slate-50 p-3">
            <div className="font-semibold text-slate-900">{compactLine([asString(item.name), asString(item.role)]) || '未填写项目'}</div>
            {asString(item.time) && <div className="mt-1 text-sm text-slate-500">{asString(item.time)}</div>}
            {asString(item.description) && <p className="mt-2 text-sm leading-6 text-slate-600">{asString(item.description)}</p>}
            {asStringArray(item.tech_stack).length > 0 && (
              <div className="mt-2 flex flex-wrap gap-2">
                {asStringArray(item.tech_stack).map((skill) => <Badge key={skill} tone="neutral">{skill}</Badge>)}
              </div>
            )}
            <PointPreview points={asRecordArray(item.interview_points)} />
          </div>
        ))}
      </PreviewSection>

      <section className="rounded-lg border border-slate-200 bg-white p-4">
        <h3 className="mb-3 font-semibold text-slate-950">技能与自我评价</h3>
        <div className="flex flex-wrap gap-2">
          {skills.map((skill) => <Badge key={skill} tone="info">{skill}</Badge>)}
          {skills.length === 0 && <span className="text-sm text-slate-500">暂无技能关键词</span>}
        </div>
        {asString(data.summary) && <p className="mt-4 text-sm leading-7 text-slate-700">{asString(data.summary)}</p>}
      </section>
    </div>
  )
}

function PreviewSection({
  title,
  emptyTitle,
  children,
}: {
  title: string
  emptyTitle: string
  children: ReactNode[]
}) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4">
      <h3 className="mb-3 font-semibold text-slate-950">{title}</h3>
      <div className="space-y-3">
        {children.length > 0 ? children : <EmptyState title={emptyTitle} />}
      </div>
    </section>
  )
}

function PointPreview({ points }: { points: Array<Record<string, unknown>> }) {
  if (points.length === 0) return null
  return (
    <div className="mt-3 rounded-md border border-slate-200 bg-white p-3">
      <div className="mb-2 text-xs font-semibold text-slate-500">可面试要点</div>
      <div className="space-y-2">
        {points.map((point, index) => (
          <div key={index} className="text-sm leading-6 text-slate-600">
            <span className="font-semibold text-slate-900">{asString(point.title) || `要点 ${index + 1}`}：</span>
            {asString(point.description) || '-'}
          </div>
        ))}
      </div>
    </div>
  )
}
