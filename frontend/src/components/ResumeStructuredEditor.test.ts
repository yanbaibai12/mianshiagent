import { describe, expect, it } from 'vitest'

import { normalizeResumeData } from './ResumeStructuredEditor'

describe('normalizeResumeData', () => {
  it('normalizes invalid section values without inventing resume facts', () => {
    const result = normalizeResumeData({
      personal: 'invalid',
      education: [null, { school: '同济大学' }],
      experience: 'invalid',
      projects: [{ name: '面试 Agent' }],
      skills: 'Python，FastAPI; Redis',
      summary: 2026,
      evidence_version: 'v1',
    })

    expect(result.personal).toEqual({})
    expect(result.education).toEqual([{}, { school: '同济大学' }])
    expect(result.experience).toEqual([])
    expect(result.projects).toEqual([{ name: '面试 Agent' }])
    expect(result.skills).toEqual(['Python', 'FastAPI', 'Redis'])
    expect(result.summary).toBe('2026')
    expect(result.evidence_version).toBe('v1')
  })

  it('returns independent records so editing does not mutate the source object', () => {
    const source = {
      personal: { name: '候选人' },
      projects: [{ name: '原项目' }],
      skills: ['Python'],
    }

    const result = normalizeResumeData(source)
    result.personal!.name = '已修改'
    result.projects![0].name = '新项目'

    expect(source.personal.name).toBe('候选人')
    expect(source.projects[0].name).toBe('原项目')
  })

  it('uses safe empty defaults for null input', () => {
    expect(normalizeResumeData(null)).toEqual({
      personal: {},
      education: [],
      experience: [],
      projects: [],
      skills: [],
      summary: '',
    })
  })
})
