import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import BotConfirmModals, { type BotConfirmModalState } from '../BotConfirmModals'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: unknown) => {
      if (typeof opts === 'object' && opts && 'defaultValue' in (opts as Record<string, unknown>)) {
        return (opts as { defaultValue: string }).defaultValue
      }
      if (typeof opts === 'object' && opts && 'name' in (opts as Record<string, unknown>)) {
        const o = opts as { name?: string; symbol?: string; count?: number }
        return `${key}::${o.name || ''}${o.symbol || ''}${o.count ?? ''}`
      }
      return key
    },
  }),
}))

const baseProps = {
  modal: null as BotConfirmModalState,
  deletePending: false,
  closePositionPending: false,
  stopPending: false,
  onDeleteConfirm: vi.fn(),
  onClosePositionConfirm: vi.fn(),
  onStopConfirm: vi.fn(),
  onHlGateConfirm: vi.fn(),
  onDismiss: vi.fn(),
}

describe('BotConfirmModals', () => {
  it('renders no dialog when modal is null', () => {
    render(<BotConfirmModals {...baseProps} />)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('opens delete dialog when modal.type=delete', () => {
    render(
      <BotConfirmModals {...baseProps} modal={{ type: 'delete', id: 1, name: 'MyBot' }} />,
    )
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByText('bots.deleteBot')).toBeInTheDocument()
  })

  it('opens close-position dialog when modal.type=close-position', () => {
    render(
      <BotConfirmModals {...baseProps} modal={{ type: 'close-position', id: 1, name: 'MyBot', symbol: 'BTCUSDT' }} />,
    )
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getAllByText(/bots\.closePosition/)[0]).toBeInTheDocument()
  })

  it('opens stop dialog when modal.type=stop', () => {
    render(
      <BotConfirmModals {...baseProps} modal={{ type: 'stop', id: 1, name: 'MyBot', openTrades: 0 }} />,
    )
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByText('bots.stopBot')).toBeInTheDocument()
  })

  it('opens hl-gate dialog when modal.type=hl-gate', () => {
    render(
      <BotConfirmModals {...baseProps} modal={{ type: 'hl-gate', id: 1, name: 'MyBot' }} />,
    )
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByText('hlSetup.setupRequiredTitle')).toBeInTheDocument()
  })

  it('calls onDeleteConfirm when delete confirm button clicked', () => {
    const onDeleteConfirm = vi.fn()
    render(
      <BotConfirmModals
        {...baseProps}
        modal={{ type: 'delete', id: 1, name: 'MyBot' }}
        onDeleteConfirm={onDeleteConfirm}
      />,
    )
    fireEvent.click(screen.getByText('bots.delete'))
    expect(onDeleteConfirm).toHaveBeenCalled()
  })
})
