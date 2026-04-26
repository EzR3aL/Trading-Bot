import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import DataSourceCategoryGrid from '../DataSourceCategoryGrid'
import type { ServiceStatus } from '../../../types'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: string) => fallback || key,
  }),
}))

const make = (key: string, label: string, category: string, reachable = true, latency = 100): [string, ServiceStatus] => [
  key,
  { type: 'data_source', label, reachable, latency_ms: latency, category } as unknown as ServiceStatus,
]

describe('DataSourceCategoryGrid', () => {
  it('renders the dataSources heading and online count', () => {
    render(<DataSourceCategoryGrid dsItems={[make('s1', 'Service One', 'sentiment')]} />)
    expect(screen.getByText('settings.dataSources')).toBeInTheDocument()
    expect(screen.getAllByText('1/1').length).toBeGreaterThan(0)
  })

  it('groups services into known categories', () => {
    render(<DataSourceCategoryGrid dsItems={[
      make('s1', 'Sent A', 'sentiment'),
      make('s2', 'Fut A', 'futures'),
    ]} />)
    expect(screen.getByText('Sentiment & News')).toBeInTheDocument()
    expect(screen.getByText('Futures Data')).toBeInTheDocument()
  })

  it('shows latency badge when latency_ms > 0', () => {
    render(<DataSourceCategoryGrid dsItems={[make('s1', 'Sent A', 'sentiment', true, 250)]} />)
    expect(screen.getByText('250ms')).toBeInTheDocument()
  })

  it('omits latency badge when latency_ms is 0', () => {
    render(<DataSourceCategoryGrid dsItems={[make('s1', 'Sent A', 'sentiment', true, 0)]} />)
    expect(screen.queryByText(/0ms/)).not.toBeInTheDocument()
  })

  it('skips empty / unknown categories', () => {
    render(<DataSourceCategoryGrid dsItems={[make('s1', 'Sent A', 'sentiment')]} />)
    // futures category should not render at all because there are no futures items
    expect(screen.queryByText('Futures Data')).not.toBeInTheDocument()
  })
})
