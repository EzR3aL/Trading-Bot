import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import ConnectionsHealthBar from '../ConnectionsHealthBar'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: string) => fallback || key,
  }),
}))

const baseProps = {
  totalOnline: 5,
  totalCount: 5,
  cbHealthy: 3,
  cbTotal: 3,
  connLoading: false,
  onRefresh: vi.fn(),
}

describe('ConnectionsHealthBar', () => {
  it('shows 100% health when all online', () => {
    render(<ConnectionsHealthBar {...baseProps} />)
    expect(screen.getByText('100%')).toBeInTheDocument()
  })

  it('renders services-online count', () => {
    render(<ConnectionsHealthBar {...baseProps} />)
    expect(screen.getByText(/5\/5/)).toBeInTheDocument()
  })

  it('shows partial-outage label when health is 80%', () => {
    render(<ConnectionsHealthBar {...baseProps} totalOnline={4} totalCount={5} />)
    expect(screen.getByText(/eingeschränkt|Partial/i)).toBeInTheDocument()
  })

  it('shows major-outage label when health is below 80%', () => {
    render(<ConnectionsHealthBar {...baseProps} totalOnline={1} totalCount={5} />)
    expect(screen.getByText(/Systemstörung|Major/i)).toBeInTheDocument()
  })

  it('shows refreshing text when connLoading=true', () => {
    render(<ConnectionsHealthBar {...baseProps} connLoading={true} />)
    expect(screen.getByText('settings.refreshing')).toBeInTheDocument()
  })

  it('calls onRefresh when refresh button clicked', () => {
    const onRefresh = vi.fn()
    render(<ConnectionsHealthBar {...baseProps} onRefresh={onRefresh} />)
    fireEvent.click(screen.getByText('settings.refreshStatus'))
    expect(onRefresh).toHaveBeenCalled()
  })

  it('shows 0% health when totalCount is 0', () => {
    render(<ConnectionsHealthBar {...baseProps} totalOnline={0} totalCount={0} />)
    expect(screen.getByText('0%')).toBeInTheDocument()
  })
})
