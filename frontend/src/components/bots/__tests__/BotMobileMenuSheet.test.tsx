import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import BotMobileMenuSheet from '../BotMobileMenuSheet'
import type { BotStatus } from '../types'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}))

const bot: BotStatus = {
  bot_config_id: 7,
  name: 'TestBot',
  strategy_type: 'edge_indicator',
  exchange_type: 'bitget',
  mode: 'demo',
  trading_pairs: ['BTC/USDT'],
  status: 'stopped',
  error_message: null,
  started_at: null,
  last_analysis: null,
  trades_today: 0,
  is_enabled: true,
  total_trades: 0,
  total_pnl: 0,
  total_fees: 0,
  total_funding: 0,
  open_trades: 0,
}

const baseProps = {
  open: true,
  bot,
  onClose: vi.fn(),
  onEdit: vi.fn(),
  onDuplicate: vi.fn(),
  onDelete: vi.fn(),
}

describe('BotMobileMenuSheet', () => {
  it('renders bot name as the sheet title when open', () => {
    render(<BotMobileMenuSheet {...baseProps} />)
    expect(screen.getByText('TestBot')).toBeInTheDocument()
  })

  it('renders edit/duplicate/delete actions', () => {
    render(<BotMobileMenuSheet {...baseProps} />)
    expect(screen.getByText('bots.edit')).toBeInTheDocument()
    expect(screen.getByText('bots.duplicate')).toBeInTheDocument()
    expect(screen.getByText('bots.delete')).toBeInTheDocument()
  })

  it('applies translate-y-0 when open', () => {
    const { container } = render(<BotMobileMenuSheet {...baseProps} open={true} />)
    const root = container.firstChild as HTMLElement
    expect(root.className).toContain('translate-y-0')
  })

  it('applies translate-y-full when closed', () => {
    const { container } = render(<BotMobileMenuSheet {...baseProps} open={false} />)
    const root = container.firstChild as HTMLElement
    expect(root.className).toContain('translate-y-full')
  })

  it('calls onClose then onEdit when Edit clicked', () => {
    const onClose = vi.fn()
    const onEdit = vi.fn()
    render(<BotMobileMenuSheet {...baseProps} onClose={onClose} onEdit={onEdit} />)
    fireEvent.click(screen.getByText('bots.edit'))
    expect(onClose).toHaveBeenCalled()
    expect(onEdit).toHaveBeenCalledWith(7)
  })

  it('calls onDuplicate with bot id when Duplicate clicked', () => {
    const onDuplicate = vi.fn()
    render(<BotMobileMenuSheet {...baseProps} onDuplicate={onDuplicate} />)
    fireEvent.click(screen.getByText('bots.duplicate'))
    expect(onDuplicate).toHaveBeenCalledWith(7)
  })

  it('calls onDelete with id and name when Delete clicked', () => {
    const onDelete = vi.fn()
    render(<BotMobileMenuSheet {...baseProps} onDelete={onDelete} />)
    fireEvent.click(screen.getByText('bots.delete'))
    expect(onDelete).toHaveBeenCalledWith(7, 'TestBot')
  })

  it('disables Edit and Delete when bot is running', () => {
    render(<BotMobileMenuSheet {...baseProps} bot={{ ...bot, status: 'running' }} />)
    expect(screen.getByText('bots.edit').closest('button')).toBeDisabled()
    expect(screen.getByText('bots.delete').closest('button')).toBeDisabled()
  })

  it('renders nothing inside the sheet when bot is null', () => {
    render(<BotMobileMenuSheet {...baseProps} bot={null} />)
    expect(screen.queryByText('bots.edit')).not.toBeInTheDocument()
  })
})
