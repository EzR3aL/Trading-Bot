import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import ExchangeLogo, { ExchangeIcon } from '../ExchangeLogo'

describe('ExchangeIcon', () => {
  it('should render Bitget logo with correct aria-label', () => {
    render(<ExchangeIcon exchange="bitget" />)

    expect(screen.getByRole('img', { name: 'Bitget' })).toBeInTheDocument()
  })

  it('should render Hyperliquid logo with correct aria-label', () => {
    render(<ExchangeIcon exchange="hyperliquid" />)

    expect(screen.getByRole('img', { name: 'Hyperliquid' })).toBeInTheDocument()
  })

  it('should render Weex logo with correct aria-label', () => {
    render(<ExchangeIcon exchange="weex" />)

    expect(screen.getByRole('img', { name: 'Weex' })).toBeInTheDocument()
  })

  it('should render BingX logo with correct aria-label', () => {
    render(<ExchangeIcon exchange="bingx" />)

    expect(screen.getByRole('img', { name: 'BingX' })).toBeInTheDocument()
  })

  it('should render Bitunix logo with correct aria-label', () => {
    render(<ExchangeIcon exchange="bitunix" />)

    expect(screen.getByRole('img', { name: 'Bitunix' })).toBeInTheDocument()
  })

  it('should return null for unknown exchange', () => {
    const { container } = render(<ExchangeIcon exchange="unknown_exchange" />)

    expect(container.firstChild).toBeNull()
  })

  it('should handle case-insensitive exchange names', () => {
    render(<ExchangeIcon exchange="BITGET" />)

    expect(screen.getByRole('img', { name: 'Bitget' })).toBeInTheDocument()
  })
})

describe('ExchangeLogo', () => {
  it('should render logo with exchange name by default', () => {
    render(<ExchangeLogo exchange="bitget" />)

    expect(screen.getByText('Bitget')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'Bitget' })).toBeInTheDocument()
  })

  it('should hide name when showName is false', () => {
    render(<ExchangeLogo exchange="bitget" showName={false} />)

    expect(screen.queryByText('Bitget')).not.toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'Bitget' })).toBeInTheDocument()
  })

  it('should apply custom className', () => {
    const { container } = render(<ExchangeLogo exchange="bitget" className="custom-class" />)

    const wrapper = container.firstChild as HTMLElement
    expect(wrapper.className).toContain('custom-class')
  })

  it('should render raw exchange name for unknown exchanges', () => {
    render(<ExchangeLogo exchange="NewExchange" />)

    // Shows the raw exchange name as text but no icon
    expect(screen.getByText('NewExchange')).toBeInTheDocument()
  })
})
