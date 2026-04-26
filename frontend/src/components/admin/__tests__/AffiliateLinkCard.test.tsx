import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import AffiliateLinkCard from '../AffiliateLinkCard'
import type { AffiliateForm, AffiliateLinkSummary } from '../types'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: string) => fallback || key,
  }),
}))

vi.mock('../../ui/ExchangeLogo', () => ({
  ExchangeIcon: ({ exchange }: { exchange: string }) => <span data-testid={`exch-${exchange}`} />,
}))

const emptyForm: AffiliateForm = { url: '', label: '', active: true, uidRequired: false }
const filledForm: AffiliateForm = { url: 'https://aff', label: 'My Label', active: true, uidRequired: true }
const summary: AffiliateLinkSummary = { affiliate_url: 'https://aff', label: 'My Label', is_active: true }

const baseProps = {
  exchange: 'bitget',
  form: emptyForm,
  linkSummary: undefined,
  open: false,
  saving: false,
  onToggleOpen: vi.fn(),
  onChangeForm: vi.fn(),
  onSave: vi.fn(),
  onDelete: vi.fn(),
}

describe('AffiliateLinkCard', () => {
  it('shows "notConfigured" badge when no linkSummary', () => {
    render(<AffiliateLinkCard {...baseProps} />)
    expect(screen.getByText('settings.notConfigured')).toBeInTheDocument()
  })

  it('shows "configured" badge when linkSummary present', () => {
    render(<AffiliateLinkCard {...baseProps} linkSummary={summary} />)
    expect(screen.getByText('settings.configured')).toBeInTheDocument()
  })

  it('hides body when open=false', () => {
    render(<AffiliateLinkCard {...baseProps} open={false} />)
    expect(screen.queryByPlaceholderText('https://...')).not.toBeInTheDocument()
  })

  it('shows form inputs when open=true', () => {
    render(<AffiliateLinkCard {...baseProps} open={true} form={filledForm} />)
    expect(screen.getByPlaceholderText('https://...')).toBeInTheDocument()
    expect(screen.getByDisplayValue('https://aff')).toBeInTheDocument()
    expect(screen.getByDisplayValue('My Label')).toBeInTheDocument()
  })

  it('calls onToggleOpen when header clicked', () => {
    const onToggleOpen = vi.fn()
    render(<AffiliateLinkCard {...baseProps} onToggleOpen={onToggleOpen} />)
    const header = screen.getByText('bitget').closest('button')!
    fireEvent.click(header)
    expect(onToggleOpen).toHaveBeenCalled()
  })

  it('hides uidRequired toggle for hyperliquid', () => {
    render(<AffiliateLinkCard {...baseProps} exchange="hyperliquid" open={true} />)
    expect(screen.queryByText('affiliate.uidRequiredToggle')).not.toBeInTheDocument()
  })

  it('shows uidRequired toggle for non-hyperliquid exchanges', () => {
    render(<AffiliateLinkCard {...baseProps} exchange="bitget" open={true} />)
    expect(screen.getByText('affiliate.uidRequiredToggle')).toBeInTheDocument()
  })

  it('disables Save button when form.url is empty', () => {
    render(<AffiliateLinkCard {...baseProps} open={true} form={emptyForm} />)
    const saveBtn = screen.getByText('settings.save').closest('button')!
    expect(saveBtn).toBeDisabled()
  })

  it('shows Delete button only when linkSummary exists', () => {
    const { rerender } = render(<AffiliateLinkCard {...baseProps} open={true} form={filledForm} linkSummary={undefined} />)
    expect(screen.queryByText('Delete')).not.toBeInTheDocument()
    rerender(<AffiliateLinkCard {...baseProps} open={true} form={filledForm} linkSummary={summary} />)
    expect(screen.getByText('Delete')).toBeInTheDocument()
  })

  it('calls onSave when Save button clicked', () => {
    const onSave = vi.fn()
    render(<AffiliateLinkCard {...baseProps} open={true} form={filledForm} onSave={onSave} />)
    fireEvent.click(screen.getByText('settings.save'))
    expect(onSave).toHaveBeenCalled()
  })
})
