import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import MobileCollapsibleCard from '../MobileCollapsibleCard'

describe('MobileCollapsibleCard', () => {
  it('renders header and hides children when collapsed', () => {
    render(
      <MobileCollapsibleCard header={<span>Header</span>}>
        <span>Details</span>
      </MobileCollapsibleCard>
    )
    expect(screen.getByText('Header')).toBeDefined()
    expect(screen.queryByText('Details')).toBeNull()
  })

  it('shows children when clicked', () => {
    render(
      <MobileCollapsibleCard header={<span>Header</span>}>
        <span>Details</span>
      </MobileCollapsibleCard>
    )
    fireEvent.click(screen.getByText('Header'))
    expect(screen.getByText('Details')).toBeDefined()
  })

  it('hides children when clicked again', () => {
    render(
      <MobileCollapsibleCard header={<span>Header</span>}>
        <span>Details</span>
      </MobileCollapsibleCard>
    )
    fireEvent.click(screen.getByText('Header'))
    expect(screen.getByText('Details')).toBeDefined()
    fireEvent.click(screen.getByText('Header'))
    expect(screen.queryByText('Details')).toBeNull()
  })

  it('renders summary row when provided', () => {
    render(
      <MobileCollapsibleCard
        header={<span>Header</span>}
        summary={<span>Summary info</span>}
      >
        <span>Details</span>
      </MobileCollapsibleCard>
    )
    expect(screen.getByText('Summary info')).toBeDefined()
    expect(screen.queryByText('Details')).toBeNull()
  })

  it('supports controlled open state', () => {
    const { rerender } = render(
      <MobileCollapsibleCard header={<span>Header</span>} isOpen={false} onToggle={() => {}}>
        <span>Details</span>
      </MobileCollapsibleCard>
    )
    expect(screen.queryByText('Details')).toBeNull()

    rerender(
      <MobileCollapsibleCard header={<span>Header</span>} isOpen={true} onToggle={() => {}}>
        <span>Details</span>
      </MobileCollapsibleCard>
    )
    expect(screen.getByText('Details')).toBeDefined()
  })

  it('renders chevron that rotates when open', () => {
    const { container } = render(
      <MobileCollapsibleCard header={<span>Header</span>}>
        <span>Details</span>
      </MobileCollapsibleCard>
    )
    const chevron = container.querySelector('svg')
    expect(chevron).toBeDefined()
    expect(chevron?.classList.contains('rotate-180')).toBe(false)

    fireEvent.click(screen.getByText('Header'))
    expect(chevron?.classList.contains('rotate-180')).toBe(true)
  })
})
