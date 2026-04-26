import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import HyperliquidAdminConfigForm from '../HyperliquidAdminConfigForm'
import type { HlAdminForm, HlAdminSettings } from '../types'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: unknown) => {
      if (typeof opts === 'object' && opts && 'source' in (opts as Record<string, unknown>)) {
        return `source:${(opts as { source: string }).source}`
      }
      return key
    },
  }),
}))

vi.mock('../../ui/FilterDropdown', () => ({
  default: ({ value, onChange, ariaLabel }: { value: string; onChange: (v: string) => void; ariaLabel: string }) => (
    <select data-testid="builder-fee" aria-label={ariaLabel} value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="0">disabled</option>
      <option value="10">10</option>
      <option value="25">25</option>
    </select>
  ),
}))

const baseForm: HlAdminForm = { builder_address: '0xabc', builder_fee: 10, referral_code: 'CODE1' }
const baseProps = {
  hlAdminSettings: null as HlAdminSettings | null,
  hlAdminForm: baseForm,
  hlAdminSaving: false,
  onChangeForm: vi.fn(),
  onSave: vi.fn(),
}

describe('HyperliquidAdminConfigForm', () => {
  it('renders all 3 form fields with current values', () => {
    render(<HyperliquidAdminConfigForm {...baseProps} />)
    expect(screen.getByDisplayValue('0xabc')).toBeInTheDocument()
    expect(screen.getByDisplayValue('CODE1')).toBeInTheDocument()
    expect((screen.getByTestId('builder-fee') as HTMLSelectElement).value).toBe('10')
  })

  it('updates builder_address via onChangeForm', () => {
    const onChangeForm = vi.fn()
    render(<HyperliquidAdminConfigForm {...baseProps} onChangeForm={onChangeForm} />)
    fireEvent.change(screen.getByDisplayValue('0xabc'), { target: { value: '0xnew' } })
    expect(onChangeForm).toHaveBeenCalledWith({ ...baseForm, builder_address: '0xnew' })
  })

  it('updates builder_fee via FilterDropdown change', () => {
    const onChangeForm = vi.fn()
    render(<HyperliquidAdminConfigForm {...baseProps} onChangeForm={onChangeForm} />)
    fireEvent.change(screen.getByTestId('builder-fee'), { target: { value: '25' } })
    expect(onChangeForm).toHaveBeenCalledWith({ ...baseForm, builder_fee: 25 })
  })

  it('disables Save button when saving', () => {
    render(<HyperliquidAdminConfigForm {...baseProps} hlAdminSaving={true} />)
    const btn = screen.getByText('settings.hlSaving').closest('button')!
    expect(btn).toBeDisabled()
  })

  it('calls onSave when Save button clicked', () => {
    const onSave = vi.fn()
    render(<HyperliquidAdminConfigForm {...baseProps} onSave={onSave} />)
    fireEvent.click(screen.getByText('settings.hlSaveSettings'))
    expect(onSave).toHaveBeenCalled()
  })

  it('shows source provenance hint when sources present', () => {
    const settings: HlAdminSettings = {
      builder_address: '0xabc',
      builder_fee: 10,
      referral_code: 'CODE1',
      sources: { builder_address: 'db', builder_fee: 'env', referral_code: 'not_set' },
    }
    render(<HyperliquidAdminConfigForm {...baseProps} hlAdminSettings={settings} />)
    expect(screen.getAllByText(/source:/).length).toBeGreaterThanOrEqual(3)
  })
})
