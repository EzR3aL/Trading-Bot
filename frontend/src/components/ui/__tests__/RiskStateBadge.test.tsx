import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import RiskStateBadge from '../RiskStateBadge'
import type { RiskLegStatus } from '../../../types/riskState'

// Mock react-i18next with identity-mapped translations for assertions
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => {
      const translations: Record<string, string> = {
        'trades.riskBadges.tp': 'TP',
        'trades.riskBadges.sl': 'SL',
        'trades.riskBadges.trail': 'Trail',
        'trades.riskBadges.source.native_exchange': 'Placed on exchange',
        'trades.riskBadges.source.software_bot': 'Monitored by bot',
        'trades.riskBadges.source.manual_user': 'User-set',
        'trades.riskBadges.source.unknown': 'Unknown source',
        'trades.riskBadges.status.pending': 'Applying…',
        'trades.riskBadges.status.confirmed': 'Active',
        'trades.riskBadges.status.rejected': 'Rejected',
        'trades.riskBadges.status.cleared': 'Cleared',
        'trades.riskBadges.status.cancel_failed': 'Cancel failed',
      }
      return translations[key] || key
    },
  }),
}))

// Factory helpers for concise leg construction
const confirmed = (value: number, overrides: Partial<RiskLegStatus> = {}): RiskLegStatus => ({
  value,
  status: 'confirmed',
  source: 'native_exchange',
  ...overrides,
})

const pending = (value: number | null = null): RiskLegStatus => ({
  value,
  status: 'pending',
  source: 'native_exchange',
})

const rejected = (value: number | null, error: string): RiskLegStatus => ({
  value,
  status: 'rejected',
  source: 'native_exchange',
  error,
})

const cancelFailed = (value: number, error: string): RiskLegStatus => ({
  value,
  status: 'cancel_failed',
  source: 'native_exchange',
  error,
})

describe('RiskStateBadge', () => {
  // === Core rendering states ===

  it('renders nothing when all legs are null (idle)', () => {
    const { container } = render(
      <RiskStateBadge tp={null} sl={null} trailing={null} riskSource="unknown" />,
    )
    expect(container.firstChild).toBeNull()
  })

  it('renders only TP chip when TP is confirmed and SL/trailing are null', () => {
    render(
      <RiskStateBadge
        tp={confirmed(80000)}
        sl={null}
        trailing={null}
        riskSource="native_exchange"
      />,
    )
    expect(screen.getByText('TP')).toBeInTheDocument()
    expect(screen.queryByText('SL')).not.toBeInTheDocument()
    expect(screen.queryByText('Trail')).not.toBeInTheDocument()
    expect(screen.getByText('$80,000')).toBeInTheDocument()
  })

  it('renders only SL chip when SL is confirmed', () => {
    render(
      <RiskStateBadge
        tp={null}
        sl={confirmed(72000)}
        trailing={null}
        riskSource="native_exchange"
      />,
    )
    expect(screen.getByText('SL')).toBeInTheDocument()
    expect(screen.queryByText('TP')).not.toBeInTheDocument()
    expect(screen.getByText('$72,000')).toBeInTheDocument()
  })

  it('renders all 3 chips when TP + SL + Trailing are confirmed', () => {
    const trailingLeg: RiskLegStatus = {
      value: 78226,
      distance_atr: 1.4,
      status: 'confirmed',
      source: 'native_exchange',
    }
    render(
      <RiskStateBadge
        tp={confirmed(80000)}
        sl={confirmed(72000)}
        trailing={trailingLeg}
        riskSource="native_exchange"
      />,
    )
    expect(screen.getByText('TP')).toBeInTheDocument()
    expect(screen.getByText('SL')).toBeInTheDocument()
    expect(screen.getByText('Trail')).toBeInTheDocument()
    expect(screen.getByText(/1.4× ATR/)).toBeInTheDocument()
    expect(screen.getByText(/@ \$78,226/)).toBeInTheDocument()
  })

  // === Status-specific rendering ===

  it('renders TP pending with spinner + dotted border style', () => {
    const { container } = render(
      <RiskStateBadge
        tp={pending(80000)}
        sl={null}
        trailing={null}
        riskSource="native_exchange"
      />,
    )
    const chip = container.querySelector('[data-kind="tp"]') as HTMLElement
    expect(chip).toBeTruthy()
    expect(chip.className).toContain('border-dashed')
    expect(chip.className).toContain('animate-pulse')
    expect(chip.getAttribute('data-status')).toBe('pending')
  })

  it('renders TP rejected with red style + error in tooltip', () => {
    const { container } = render(
      <RiskStateBadge
        tp={rejected(80000, 'exchange returned INSUFFICIENT_BALANCE')}
        sl={null}
        trailing={null}
        riskSource="native_exchange"
      />,
    )
    const chip = container.querySelector('[data-kind="tp"]') as HTMLElement
    expect(chip.className).toContain('text-red-400')
    expect(chip.className).toContain('bg-red-500/10')
    expect(chip.getAttribute('title')).toContain('INSUFFICIENT_BALANCE')
    expect(chip.getAttribute('aria-label')).toContain('INSUFFICIENT_BALANCE')
  })

  it('renders Trailing cancel_failed with amber style + warning tooltip', () => {
    const { container } = render(
      <RiskStateBadge
        tp={null}
        sl={null}
        trailing={cancelFailed(78000, 'Old value still active')}
        riskSource="native_exchange"
      />,
    )
    const chip = container.querySelector('[data-kind="trailing"]') as HTMLElement
    expect(chip.className).toContain('text-amber-400')
    expect(chip.className).toContain('bg-amber-500/10')
    expect(chip.getAttribute('title')).toContain('Old value still active')
    expect(chip.getAttribute('data-status')).toBe('cancel_failed')
  })

  // === Source indicator ===

  it('shows software source via Cpu icon for software_bot trailing', () => {
    const { container } = render(
      <RiskStateBadge
        tp={null}
        sl={null}
        trailing={{
          value: 78226,
          distance_atr: 1.4,
          status: 'confirmed',
          source: 'software_bot',
        }}
        riskSource="software_bot"
      />,
    )
    const chip = container.querySelector('[data-kind="trailing"]') as HTMLElement
    expect(chip.getAttribute('data-source')).toBe('software_bot')
    expect(chip.getAttribute('aria-label')).toContain('Monitored by bot')
  })

  it('shows native source in aria-label for native_exchange TP', () => {
    const { container } = render(
      <RiskStateBadge
        tp={confirmed(80000, { source: 'native_exchange' })}
        sl={null}
        trailing={null}
        riskSource="native_exchange"
      />,
    )
    const chip = container.querySelector('[data-kind="tp"]') as HTMLElement
    expect(chip.getAttribute('aria-label')).toContain('Placed on exchange')
  })

  // === Leg-specific edge cases ===

  it('skips legs with status=cleared', () => {
    render(
      <RiskStateBadge
        tp={{ value: 80000, status: 'cleared', source: 'unknown' }}
        sl={confirmed(72000)}
        trailing={null}
        riskSource="unknown"
      />,
    )
    expect(screen.queryByText('TP')).not.toBeInTheDocument()
    expect(screen.getByText('SL')).toBeInTheDocument()
  })

  it('skips confirmed legs that have null value (no point rendering $null)', () => {
    const { container } = render(
      <RiskStateBadge
        tp={{ value: null, status: 'confirmed', source: 'unknown' }}
        sl={null}
        trailing={null}
        riskSource="unknown"
      />,
    )
    expect(container.firstChild).toBeNull()
  })

  // === Tooltip content ===

  it('embeds order_id and latency into the chip tooltip', () => {
    const { container } = render(
      <RiskStateBadge
        tp={confirmed(80000, {
          order_id: 'ORD-12345',
          latency_ms: 42,
        })}
        sl={null}
        trailing={null}
        riskSource="native_exchange"
      />,
    )
    const chip = container.querySelector('[data-kind="tp"]') as HTMLElement
    const tooltip = chip.getAttribute('title') ?? ''
    expect(tooltip).toContain('ORD-12345')
    expect(tooltip).toContain('42ms')
    expect(tooltip).toContain('Active')
  })

  // === Layout: compact vs horizontal ===

  it('applies vertical stack layout in compact mode', () => {
    const { container } = render(
      <RiskStateBadge
        tp={confirmed(80000)}
        sl={confirmed(72000)}
        trailing={null}
        riskSource="native_exchange"
        compact
      />,
    )
    const root = container.firstChild as HTMLElement
    expect(root.getAttribute('data-compact')).toBe('true')
    expect(root.className).toContain('flex-col')
  })

  it('applies horizontal layout when compact is false', () => {
    const { container } = render(
      <RiskStateBadge
        tp={confirmed(80000)}
        sl={confirmed(72000)}
        trailing={null}
        riskSource="native_exchange"
      />,
    )
    const root = container.firstChild as HTMLElement
    expect(root.getAttribute('data-compact')).toBe('false')
    expect(root.className).toContain('flex-row')
  })

  // === Trailing-specific formatting ===

  it('formats trailing with only distance_pct when ATR is absent', () => {
    render(
      <RiskStateBadge
        tp={null}
        sl={null}
        trailing={{
          value: 78000,
          distance_pct: 2.5,
          status: 'confirmed',
          source: 'software_bot',
        }}
        riskSource="software_bot"
      />,
    )
    expect(screen.getByText(/2\.50%/)).toBeInTheDocument()
    expect(screen.getByText(/@ \$78,000/)).toBeInTheDocument()
  })

  // === Accessibility ===

  it('each chip has role=status and is focusable via tabIndex=0', () => {
    const { container } = render(
      <RiskStateBadge
        tp={confirmed(80000)}
        sl={null}
        trailing={null}
        riskSource="native_exchange"
      />,
    )
    const chip = container.querySelector('[data-kind="tp"]') as HTMLElement
    expect(chip.getAttribute('role')).toBe('status')
    expect(chip.getAttribute('tabindex')).toBe('0')
    expect(chip.getAttribute('aria-label')).toBeTruthy()
  })

  it('outer group has aria-label and role=group for screen readers', () => {
    const { container } = render(
      <RiskStateBadge
        tp={confirmed(80000)}
        sl={null}
        trailing={null}
        riskSource="native_exchange"
      />,
    )
    const group = container.firstChild as HTMLElement
    expect(group.getAttribute('role')).toBe('group')
    expect(group.getAttribute('aria-label')).toBe('Risk state')
  })
})
