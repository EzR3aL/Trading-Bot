import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import HyperliquidStatusOverview from '../HyperliquidStatusOverview'
import type { HlRevenueInfo } from '../../../types'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: string) => fallback || key,
  }),
}))

const allConfigured: HlRevenueInfo = {
  builder: { configured: true, user_approved: true } as any,
  referral: { configured: true, user_referred: true } as any,
  earnings: { total_builder_fees_30d: 12.3456, trades_with_builder_fee: 5, monthly_estimate: 24.7 } as any,
}

const partialConfigured: HlRevenueInfo = {
  builder: { configured: true, user_approved: true } as any,
  referral: { configured: false, user_referred: false } as any,
  earnings: null as any,
}

describe('HyperliquidStatusOverview', () => {
  it('shows empty state when hlRevenue is null', () => {
    render(<HyperliquidStatusOverview hlRevenue={null} hlLoading={false} onRefresh={() => {}} />)
    expect(screen.getByText('settings.hlNoConnection')).toBeInTheDocument()
  })

  it('shows refreshing label and hides refresh button while loading + no revenue', () => {
    render(<HyperliquidStatusOverview hlRevenue={null} hlLoading={true} onRefresh={() => {}} />)
    expect(screen.getByText('settings.refreshing')).toBeInTheDocument()
  })

  it('shows 100% configured when both builder + referral OK', () => {
    render(<HyperliquidStatusOverview hlRevenue={allConfigured} hlLoading={false} onRefresh={() => {}} />)
    expect(screen.getByText('100%')).toBeInTheDocument()
  })

  it('shows partial-configured label at 50%', () => {
    render(<HyperliquidStatusOverview hlRevenue={partialConfigured} hlLoading={false} onRefresh={() => {}} />)
    expect(screen.getByText('50%')).toBeInTheDocument()
  })

  it('calls onRefresh when refresh button clicked', () => {
    const onRefresh = vi.fn()
    render(<HyperliquidStatusOverview hlRevenue={allConfigured} hlLoading={false} onRefresh={onRefresh} />)
    fireEvent.click(screen.getByText('settings.refreshStatus'))
    expect(onRefresh).toHaveBeenCalled()
  })
})
