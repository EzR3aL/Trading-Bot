import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import CircuitBreakersGrid from '../CircuitBreakersGrid'
import type { ConnectionsStatusResponse } from '../../../types'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}))

type CB = ConnectionsStatusResponse['circuit_breakers'][string]

const make = (name: string, state: 'closed' | 'open' | 'half_open'): [string, CB] => [
  name,
  { name, state, failure_count: 0, opened_at: null } as CB,
]

describe('CircuitBreakersGrid', () => {
  it('renders heading and total count badge', () => {
    render(<CircuitBreakersGrid cbEntries={[make('cb1', 'closed'), make('cb2', 'open')]} cbHealthy={1} />)
    expect(screen.getByText('settings.circuitBreakers')).toBeInTheDocument()
    expect(screen.getByText('1/2')).toBeInTheDocument()
  })

  it('renders one card per breaker with name', () => {
    render(<CircuitBreakersGrid cbEntries={[make('cb1', 'closed'), make('cb2', 'open')]} cbHealthy={1} />)
    expect(screen.getByText('cb1')).toBeInTheDocument()
    expect(screen.getByText('cb2')).toBeInTheDocument()
  })

  it('uses circuitClosed label for closed breaker', () => {
    render(<CircuitBreakersGrid cbEntries={[make('cb1', 'closed')]} cbHealthy={1} />)
    expect(screen.getByText('settings.circuitClosed')).toBeInTheDocument()
  })

  it('uses circuitOpen label for open breaker', () => {
    render(<CircuitBreakersGrid cbEntries={[make('cb1', 'open')]} cbHealthy={0} />)
    expect(screen.getByText('settings.circuitOpen')).toBeInTheDocument()
  })

  it('uses circuitHalfOpen label for half-open breaker', () => {
    render(<CircuitBreakersGrid cbEntries={[make('cb1', 'half_open')]} cbHealthy={0} />)
    expect(screen.getByText('settings.circuitHalfOpen')).toBeInTheDocument()
  })
})
