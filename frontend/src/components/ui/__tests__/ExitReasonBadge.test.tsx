import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import ExitReasonBadge from '../ExitReasonBadge'

// Mock react-i18next
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => {
      const translations: Record<string, string> = {
        'trades.exitReasons.TAKE_PROFIT': 'Take Profit',
        'trades.exitReasons.STOP_LOSS': 'Stop Loss',
        'trades.exitReasons.TRAILING_STOP': 'Trailing Stop',
        'trades.exitReasons.STRATEGY_EXIT': 'Strategy Exit',
        'trades.exitReasons.EXTERNAL_CLOSE': 'External Close',
        'trades.exitReasons.MANUAL_CLOSE': 'Manual Close',
        'trades.exitReasons.unknown': 'Unknown',
      }
      return translations[key] || key
    },
  }),
}))

describe('ExitReasonBadge', () => {
  it('should render null when reason is null', () => {
    const { container } = render(<ExitReasonBadge reason={null} />)

    expect(container.firstChild).toBeNull()
  })

  it('should render Take Profit badge', () => {
    render(<ExitReasonBadge reason="TAKE_PROFIT" />)

    expect(screen.getByText('Take Profit')).toBeInTheDocument()
  })

  it('should render Stop Loss badge', () => {
    render(<ExitReasonBadge reason="STOP_LOSS" />)

    expect(screen.getByText('Stop Loss')).toBeInTheDocument()
  })

  it('should render Trailing Stop badge', () => {
    render(<ExitReasonBadge reason="TRAILING_STOP" />)

    expect(screen.getByText('Trailing Stop')).toBeInTheDocument()
  })

  it('should render Strategy Exit badge', () => {
    render(<ExitReasonBadge reason="STRATEGY_EXIT" />)

    expect(screen.getByText('Strategy Exit')).toBeInTheDocument()
  })

  it('should render External Close badge', () => {
    render(<ExitReasonBadge reason="EXTERNAL_CLOSE" />)

    expect(screen.getByText('External Close')).toBeInTheDocument()
  })

  it('should render Manual Close badge', () => {
    render(<ExitReasonBadge reason="MANUAL_CLOSE" />)

    expect(screen.getByText('Manual Close')).toBeInTheDocument()
  })

  it('should render Unknown for unrecognized reason', () => {
    render(<ExitReasonBadge reason="SOMETHING_ELSE" />)

    expect(screen.getByText('Unknown')).toBeInTheDocument()
  })

  it('should match reason by prefix (e.g. STRATEGY_EXIT with extra info)', () => {
    render(<ExitReasonBadge reason="STRATEGY_EXIT [BotName] some reason" />)

    expect(screen.getByText('Strategy Exit')).toBeInTheDocument()
  })

  it('should apply emerald styles for TAKE_PROFIT', () => {
    const { container } = render(<ExitReasonBadge reason="TAKE_PROFIT" />)

    const badge = container.firstChild as HTMLElement
    expect(badge.className).toContain('bg-emerald-500/10')
    expect(badge.className).toContain('text-emerald-400')
  })

  it('should apply red styles for STOP_LOSS', () => {
    const { container } = render(<ExitReasonBadge reason="STOP_LOSS" />)

    const badge = container.firstChild as HTMLElement
    expect(badge.className).toContain('bg-red-500/10')
    expect(badge.className).toContain('text-red-400')
  })

  it('should apply blue styles for TRAILING_STOP', () => {
    const { container } = render(<ExitReasonBadge reason="TRAILING_STOP" />)

    const badge = container.firstChild as HTMLElement
    expect(badge.className).toContain('bg-blue-500/10')
    expect(badge.className).toContain('text-blue-400')
  })

  it('should render compact variant', () => {
    const { container } = render(<ExitReasonBadge reason="TAKE_PROFIT" compact />)

    const badge = container.firstChild as HTMLElement
    // Compact should not have the px-2.5 / rounded-full badge styling
    expect(badge.className).not.toContain('rounded-full')
    expect(screen.getByText('Take Profit')).toBeInTheDocument()
  })
})
