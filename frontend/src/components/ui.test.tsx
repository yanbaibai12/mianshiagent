import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { ProgressBar, cn } from './ui'

describe('cn', () => {
  it('joins only truthy class names in their original order', () => {
    expect(cn('card', false, undefined, 'card-active', null)).toBe('card card-active')
  })
})

describe('ProgressBar', () => {
  it.each([
    { input: -10, expected: '0%' },
    { input: 42, expected: '42%' },
    { input: 130, expected: '100%' },
  ])('clamps $input to $expected', ({ input, expected }) => {
    const { container } = render(<ProgressBar value={input} />)
    const fill = container.querySelector('.progress-fill') as HTMLElement | null

    expect(fill).not.toBeNull()
    expect(fill?.style.width).toBe(expected)
  })
})
