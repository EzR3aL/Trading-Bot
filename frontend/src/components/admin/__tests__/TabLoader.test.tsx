import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import TabLoader from '../TabLoader'

describe('TabLoader', () => {
  it('renders a spinner element', () => {
    const { container } = render(<TabLoader />)
    const spinner = container.querySelector('.animate-spin')
    expect(spinner).toBeTruthy()
  })

  it('uses centered flex layout', () => {
    const { container } = render(<TabLoader />)
    const root = container.firstChild as HTMLElement
    expect(root.className).toContain('flex')
    expect(root.className).toContain('items-center')
    expect(root.className).toContain('justify-center')
  })
})
