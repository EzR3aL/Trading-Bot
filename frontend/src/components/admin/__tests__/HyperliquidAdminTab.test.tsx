import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import HyperliquidAdminTab from '../HyperliquidAdminTab'
import type { HlRevenueInfo } from '../../../types'
import type { HlAdminForm, HlAdminSettings } from '../types'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}))

vi.mock('../HyperliquidStatusOverview', () => ({
  default: () => <div data-testid="status-overview" />,
}))

vi.mock('../HyperliquidAdminConfigForm', () => ({
  default: () => <div data-testid="config-form" />,
}))

const baseForm: HlAdminForm = { builder_address: '0xabc', builder_fee: 10, referral_code: 'CODE' }
const baseSettings: HlAdminSettings = { ...baseForm, sources: {} }

describe('HyperliquidAdminTab', () => {
  it('renders status overview and config form', () => {
    render(
      <HyperliquidAdminTab
        hlRevenue={null}
        hlLoading={false}
        hlAdminSettings={baseSettings}
        hlAdminForm={baseForm}
        hlAdminSaving={false}
        onRefreshRevenue={() => {}}
        onChangeAdminForm={() => {}}
        onSaveAdminSettings={() => {}}
      />,
    )
    expect(screen.getByTestId('status-overview')).toBeInTheDocument()
    expect(screen.getByTestId('config-form')).toBeInTheDocument()
  })

  it('renders earnings tiles when hlRevenue.earnings present', () => {
    const revenue: HlRevenueInfo = {
      builder: { configured: true, user_approved: true } as any,
      referral: { configured: true, user_referred: true } as any,
      earnings: { total_builder_fees_30d: 12.3456, trades_with_builder_fee: 7, monthly_estimate: 24.5 } as any,
    }
    render(
      <HyperliquidAdminTab
        hlRevenue={revenue}
        hlLoading={false}
        hlAdminSettings={baseSettings}
        hlAdminForm={baseForm}
        hlAdminSaving={false}
        onRefreshRevenue={() => {}}
        onChangeAdminForm={() => {}}
        onSaveAdminSettings={() => {}}
      />,
    )
    expect(screen.getByText('settings.hlEarnings')).toBeInTheDocument()
    expect(screen.getByText('$12.3456')).toBeInTheDocument()
    expect(screen.getByText('7')).toBeInTheDocument()
  })

  it('omits earnings tiles when no earnings data', () => {
    render(
      <HyperliquidAdminTab
        hlRevenue={null}
        hlLoading={false}
        hlAdminSettings={baseSettings}
        hlAdminForm={baseForm}
        hlAdminSaving={false}
        onRefreshRevenue={() => {}}
        onChangeAdminForm={() => {}}
        onSaveAdminSettings={() => {}}
      />,
    )
    expect(screen.queryByText('settings.hlEarnings')).not.toBeInTheDocument()
  })
})
