import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import AdminTabs from '../AdminTabs'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}))

describe('AdminTabs', () => {
  it('renders all tab labels', () => {
    render(<AdminTabs activeTab="users" onChange={() => {}} />)
    expect(screen.getByText('admin.users')).toBeInTheDocument()
    expect(screen.getByText('admin.revenue')).toBeInTheDocument()
    expect(screen.getByText('settings.connections')).toBeInTheDocument()
    expect(screen.getByText('settings.affiliateLinks')).toBeInTheDocument()
    expect(screen.getByText('settings.hyperliquid')).toBeInTheDocument()
    expect(screen.getByText('broadcast.title')).toBeInTheDocument()
  })

  it('highlights the active tab via primary color class', () => {
    render(<AdminTabs activeTab="revenue" onChange={() => {}} />)
    const activeButton = screen.getByText('admin.revenue').closest('button')!
    expect(activeButton.className).toContain('bg-primary-600')
  })

  it('does not highlight inactive tabs with primary color', () => {
    render(<AdminTabs activeTab="revenue" onChange={() => {}} />)
    const inactive = screen.getByText('admin.users').closest('button')!
    expect(inactive.className).not.toContain('bg-primary-600')
  })

  it('calls onChange with the clicked tab key', () => {
    const onChange = vi.fn()
    render(<AdminTabs activeTab="users" onChange={onChange} />)
    fireEvent.click(screen.getByText('settings.connections'))
    expect(onChange).toHaveBeenCalledWith('connections')
  })
})
