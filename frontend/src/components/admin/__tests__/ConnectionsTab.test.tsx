import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import ConnectionsTab from '../ConnectionsTab'
import type { ConnectionsStatusResponse } from '../../../types'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: string) => fallback || key,
  }),
}))

vi.mock('../ConnectionsHealthBar', () => ({
  default: ({ onRefresh }: { onRefresh: () => void }) => (
    <button data-testid="health-bar" onClick={onRefresh}>health-bar</button>
  ),
}))
vi.mock('../DataSourceCategoryGrid', () => ({
  default: () => <div data-testid="data-source-grid" />,
}))
vi.mock('../ExchangeAndNotificationsRow', () => ({
  default: () => <div data-testid="exch-notif-row" />,
}))
vi.mock('../CircuitBreakersGrid', () => ({
  default: () => <div data-testid="cb-grid" />,
}))

describe('ConnectionsTab', () => {
  it('shows empty state with refresh CTA when connStatus is null', () => {
    const onRefresh = vi.fn()
    render(<ConnectionsTab connStatus={null} connLoading={false} onRefresh={onRefresh} />)
    expect(screen.getByText('settings.connectionsDesc')).toBeInTheDocument()
    fireEvent.click(screen.getByText('settings.refreshStatus'))
    expect(onRefresh).toHaveBeenCalled()
  })

  it('shows refreshing label when loading and no status', () => {
    render(<ConnectionsTab connStatus={null} connLoading={true} onRefresh={() => {}} />)
    expect(screen.getByText('settings.refreshing')).toBeInTheDocument()
  })

  it('renders sub-components when connStatus loaded', () => {
    const status: ConnectionsStatusResponse = {
      services: {
        ds1: { type: 'data_source', label: 'DS1', reachable: true, latency_ms: 100, configured: true } as any,
        exch1: { type: 'exchange', label: 'EXCH1', reachable: true, latency_ms: 80, configured: true } as any,
        notif1: { type: 'notification', label: 'NOTIF1', reachable: true, latency_ms: 50 } as any,
      },
      circuit_breakers: {
        cb1: { name: 'cb1', state: 'closed', failure_count: 0, opened_at: null } as any,
      },
    } as ConnectionsStatusResponse
    render(<ConnectionsTab connStatus={status} connLoading={false} onRefresh={() => {}} />)
    expect(screen.getByTestId('health-bar')).toBeInTheDocument()
    expect(screen.getByTestId('data-source-grid')).toBeInTheDocument()
    expect(screen.getByTestId('exch-notif-row')).toBeInTheDocument()
    expect(screen.getByTestId('cb-grid')).toBeInTheDocument()
  })

  it('omits CircuitBreakersGrid when there are no breakers', () => {
    const status: ConnectionsStatusResponse = {
      services: {
        ds1: { type: 'data_source', label: 'DS1', reachable: true, latency_ms: 100, configured: true } as any,
      },
      circuit_breakers: {},
    } as ConnectionsStatusResponse
    render(<ConnectionsTab connStatus={status} connLoading={false} onRefresh={() => {}} />)
    expect(screen.queryByTestId('cb-grid')).not.toBeInTheDocument()
  })
})
