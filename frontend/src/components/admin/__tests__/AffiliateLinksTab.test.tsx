import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import AffiliateLinksTab from '../AffiliateLinksTab'
import type { AffiliateForm, AffiliateLinkSummary } from '../types'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: string) => fallback || key,
  }),
}))

// Stub child components — we only verify wiring/state from the tab perspective
vi.mock('../AffiliateLinkCard', () => ({
  default: ({ exchange, onSave }: { exchange: string; onSave: () => void }) => (
    <button data-testid={`card-${exchange}`} onClick={onSave}>card-{exchange}</button>
  ),
}))

vi.mock('../AdminUidTable', () => ({
  default: () => <div data-testid="uid-table" />,
}))

const formFor = (url: string): AffiliateForm => ({ url, label: '', active: true, uidRequired: false })

const baseProps = {
  affiliateLinks: {} as Record<string, AffiliateLinkSummary>,
  affiliateForms: {
    bitget: formFor(''),
    weex: formFor(''),
    hyperliquid: formFor(''),
    bitunix: formFor(''),
    bingx: formFor(''),
  } as Record<string, AffiliateForm>,
  affiliateCardOpen: {} as Record<string, boolean>,
  saving: false,
  adminUids: [],
  adminUidStats: { total: 0, verified: 0, pending: 0 },
  adminUidPage: 1,
  adminUidPages: 1,
  adminUidTotal: 0,
  adminUidSearch: '',
  adminUidFilter: 'all' as const,
  onChangeForm: vi.fn(),
  onToggleCard: vi.fn(),
  onSaveOne: vi.fn(),
  onSaveAll: vi.fn(),
  onDelete: vi.fn(),
  onSearchChange: vi.fn(),
  onFilterChange: vi.fn(),
  onPageChange: vi.fn(),
  onVerify: vi.fn(),
}

describe('AffiliateLinksTab', () => {
  it('renders one AffiliateLinkCard per supported exchange', () => {
    render(<AffiliateLinksTab {...baseProps} />)
    expect(screen.getByTestId('card-bitget')).toBeInTheDocument()
    expect(screen.getByTestId('card-weex')).toBeInTheDocument()
    expect(screen.getByTestId('card-hyperliquid')).toBeInTheDocument()
    expect(screen.getByTestId('card-bitunix')).toBeInTheDocument()
    expect(screen.getByTestId('card-bingx')).toBeInTheDocument()
  })

  it('renders the UID table', () => {
    render(<AffiliateLinksTab {...baseProps} />)
    expect(screen.getByTestId('uid-table')).toBeInTheDocument()
  })

  it('disables Save All when no form has a URL', () => {
    render(<AffiliateLinksTab {...baseProps} />)
    const saveAll = screen.getByText('settings.saveAll').closest('button')!
    expect(saveAll).toBeDisabled()
  })

  it('enables Save All when at least one form has a URL', () => {
    render(<AffiliateLinksTab {...baseProps} affiliateForms={{ ...baseProps.affiliateForms, bitget: formFor('https://x') }} />)
    const saveAll = screen.getByText('settings.saveAll').closest('button')!
    expect(saveAll).not.toBeDisabled()
  })

  it('calls onSaveAll when Save All clicked', () => {
    const onSaveAll = vi.fn()
    render(<AffiliateLinksTab {...baseProps} affiliateForms={{ ...baseProps.affiliateForms, bitget: formFor('https://x') }} onSaveAll={onSaveAll} />)
    fireEvent.click(screen.getByText('settings.saveAll'))
    expect(onSaveAll).toHaveBeenCalled()
  })

  it('shows configured count summary', () => {
    const links: Record<string, AffiliateLinkSummary> = {
      bitget: { affiliate_url: 'x', label: '', is_active: true },
      weex: { affiliate_url: 'y', label: '', is_active: true },
    }
    render(<AffiliateLinksTab {...baseProps} affiliateLinks={links} />)
    expect(screen.getByText(/2\/5/)).toBeInTheDocument()
  })
})
