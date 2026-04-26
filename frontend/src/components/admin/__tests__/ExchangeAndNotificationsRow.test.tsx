import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import ExchangeAndNotificationsRow from '../ExchangeAndNotificationsRow'
import type { ServiceStatus } from '../../../types'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}))

vi.mock('../../ui/ExchangeLogo', () => ({
  ExchangeIcon: ({ exchange }: { exchange: string }) => <span data-testid={`exch-${exchange}`} />,
}))

const exchSvc = (key: string, label: string, reachable: boolean, configured = true, latency = 100): [string, ServiceStatus] => [
  key,
  { type: 'exchange', label, reachable, latency_ms: latency, configured } as unknown as ServiceStatus,
]

const notifSvc = (key: string, label: string, reachable: boolean): [string, ServiceStatus] => [
  key,
  { type: 'notification', label, reachable, latency_ms: 50 } as unknown as ServiceStatus,
]

describe('ExchangeAndNotificationsRow', () => {
  it('renders exchange section header when exchItems present', () => {
    render(<ExchangeAndNotificationsRow exchItems={[exchSvc('exchange_bitget', 'Bitget', true)]} notifItems={[]} />)
    expect(screen.getByText('settings.exchangeApi')).toBeInTheDocument()
  })

  it('renders notification section header when notifItems present', () => {
    render(<ExchangeAndNotificationsRow exchItems={[]} notifItems={[notifSvc('telegram', 'Telegram', true)]} />)
    expect(screen.getByText('settings.notifications')).toBeInTheDocument()
  })

  it('shows online status for reachable exchange', () => {
    render(<ExchangeAndNotificationsRow exchItems={[exchSvc('exchange_bitget', 'Bitget', true)]} notifItems={[]} />)
    expect(screen.getByText('settings.online')).toBeInTheDocument()
  })

  it('shows offline status for unreachable exchange', () => {
    render(<ExchangeAndNotificationsRow exchItems={[exchSvc('exchange_bitget', 'Bitget', false)]} notifItems={[]} />)
    expect(screen.getByText('settings.offline')).toBeInTheDocument()
  })

  it('shows dash badge for unconfigured exchange', () => {
    render(<ExchangeAndNotificationsRow exchItems={[exchSvc('exchange_bitget', 'Bitget', false, false)]} notifItems={[]} />)
    expect(screen.getByText('—')).toBeInTheDocument()
  })

  it('renders both columns when both lists populated', () => {
    render(
      <ExchangeAndNotificationsRow
        exchItems={[exchSvc('exchange_bitget', 'Bitget', true)]}
        notifItems={[notifSvc('telegram', 'Telegram', true)]}
      />,
    )
    expect(screen.getByText('Bitget')).toBeInTheDocument()
    expect(screen.getByText('Telegram')).toBeInTheDocument()
  })
})
