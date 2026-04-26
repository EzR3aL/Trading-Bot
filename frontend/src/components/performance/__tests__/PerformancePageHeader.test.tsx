import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import PerformancePageHeader from '../PerformancePageHeader'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}))

describe('PerformancePageHeader', () => {
  it('renders the page title', () => {
    render(<PerformancePageHeader viewMode="cards" days={30} onViewModeChange={() => {}} onDaysChange={() => {}} />)
    expect(screen.getByText('performance.title')).toBeInTheDocument()
  })

  it('renders all four day-range pills', () => {
    render(<PerformancePageHeader viewMode="cards" days={30} onViewModeChange={() => {}} onDaysChange={() => {}} />)
    expect(screen.getByText('7d')).toBeInTheDocument()
    expect(screen.getByText('14d')).toBeInTheDocument()
    expect(screen.getByText('30d')).toBeInTheDocument()
    expect(screen.getByText('90d')).toBeInTheDocument()
  })

  it('highlights the active days pill', () => {
    render(<PerformancePageHeader viewMode="cards" days={30} onViewModeChange={() => {}} onDaysChange={() => {}} />)
    const active = screen.getByText('30d').closest('button')!
    expect(active.className).toContain('from-primary-600')
  })

  it('calls onDaysChange with the new value when a pill is clicked', () => {
    const onDaysChange = vi.fn()
    render(<PerformancePageHeader viewMode="cards" days={30} onViewModeChange={() => {}} onDaysChange={onDaysChange} />)
    fireEvent.click(screen.getByText('7d'))
    expect(onDaysChange).toHaveBeenCalledWith(7)
  })

  it('calls onViewModeChange with cards/grid when toggle clicked', () => {
    const onViewModeChange = vi.fn()
    render(<PerformancePageHeader viewMode="cards" days={30} onViewModeChange={onViewModeChange} onDaysChange={() => {}} />)
    fireEvent.click(screen.getByLabelText('Grid view'))
    expect(onViewModeChange).toHaveBeenCalledWith('grid')
  })

  it('marks the active view-mode toggle with bg-white/10', () => {
    render(<PerformancePageHeader viewMode="grid" days={30} onViewModeChange={() => {}} onDaysChange={() => {}} />)
    const grid = screen.getByLabelText('Grid view')
    expect(grid.className).toContain('bg-white/10')
  })
})
