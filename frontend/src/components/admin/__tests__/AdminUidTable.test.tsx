import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import AdminUidTable from '../AdminUidTable'
import type { AdminUidEntry } from '../../../types'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: string) => fallback || key,
  }),
}))

vi.mock('../../ui/ExchangeLogo', () => ({
  ExchangeIcon: ({ exchange }: { exchange: string }) => <span data-testid={`exch-${exchange}`} />,
}))

vi.mock('../../ui/Pagination', () => ({
  default: ({ page, totalPages, onPageChange }: { page: number; totalPages: number; onPageChange: (p: number) => void }) => (
    <button data-testid="pagination" onClick={() => onPageChange(page + 1)}>
      page {page}/{totalPages}
    </button>
  ),
}))

const baseUid: AdminUidEntry = {
  connection_id: 1,
  username: 'alice',
  exchange_type: 'bitget',
  affiliate_uid: '12345',
  affiliate_verified: false,
  verify_method: 'manual',
  submitted_at: '2026-04-01T00:00:00Z',
}

const baseStats = { total: 5, verified: 2, pending: 3 }

const baseProps = {
  uids: [baseUid],
  search: '',
  filter: 'all' as const,
  stats: baseStats,
  page: 1,
  totalPages: 1,
  total: 5,
  onSearchChange: vi.fn(),
  onFilterChange: vi.fn(),
  onPageChange: vi.fn(),
  onVerify: vi.fn(),
}

describe('AdminUidTable', () => {
  it('renders username + UID for each row', () => {
    render(<AdminUidTable {...baseProps} />)
    expect(screen.getByText('alice')).toBeInTheDocument()
    expect(screen.getByText('12345')).toBeInTheDocument()
  })

  it('shows pending-count badge when stats.pending > 0', () => {
    render(<AdminUidTable {...baseProps} />)
    expect(screen.getByText('3 offen')).toBeInTheDocument()
  })

  it('shows empty state when uids array is empty', () => {
    render(<AdminUidTable {...baseProps} uids={[]} />)
    expect(screen.getByText('affiliate.noUids')).toBeInTheDocument()
  })

  it('calls onSearchChange when search input changes', () => {
    const onSearchChange = vi.fn()
    render(<AdminUidTable {...baseProps} onSearchChange={onSearchChange} />)
    const input = screen.getByPlaceholderText('Username / UID...')
    fireEvent.change(input, { target: { value: 'bob' } })
    expect(onSearchChange).toHaveBeenCalledWith('bob')
  })

  it('calls onFilterChange when filter pill clicked', () => {
    const onFilterChange = vi.fn()
    render(<AdminUidTable {...baseProps} onFilterChange={onFilterChange} />)
    fireEvent.click(screen.getByText('Verifiziert'))
    expect(onFilterChange).toHaveBeenCalledWith('verified')
  })

  it('calls onVerify(true) when verify button clicked on a pending row', () => {
    const onVerify = vi.fn()
    render(<AdminUidTable {...baseProps} onVerify={onVerify} />)
    const verifyBtn = screen.getByTitle('affiliate.verifyUid')
    fireEvent.click(verifyBtn)
    expect(onVerify).toHaveBeenCalledWith(1, true)
  })

  it('renders Pagination only when totalPages > 1', () => {
    const { rerender } = render(<AdminUidTable {...baseProps} totalPages={1} />)
    expect(screen.queryByTestId('pagination')).not.toBeInTheDocument()
    rerender(<AdminUidTable {...baseProps} totalPages={3} />)
    expect(screen.getByTestId('pagination')).toBeInTheDocument()
  })
})
