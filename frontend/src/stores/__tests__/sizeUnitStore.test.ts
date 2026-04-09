import { describe, it, expect, beforeEach } from 'vitest'
import { useSizeUnitStore, formatSize } from '../sizeUnitStore'

describe('sizeUnitStore', () => {
  beforeEach(() => {
    localStorage.clear()
    // Reset store to default
    useSizeUnitStore.setState({ unit: 'token' })
  })

  it('should default to token unit', () => {
    expect(useSizeUnitStore.getState().unit).toBe('token')
  })

  it('should toggle from token to usdt', () => {
    useSizeUnitStore.getState().toggle()
    expect(useSizeUnitStore.getState().unit).toBe('usdt')
  })

  it('should toggle back from usdt to token', () => {
    useSizeUnitStore.setState({ unit: 'usdt' })
    useSizeUnitStore.getState().toggle()
    expect(useSizeUnitStore.getState().unit).toBe('token')
  })

  it('should persist unit to localStorage', () => {
    useSizeUnitStore.getState().toggle()
    expect(localStorage.getItem('sizeUnit')).toBe('usdt')

    useSizeUnitStore.getState().toggle()
    expect(localStorage.getItem('sizeUnit')).toBe('token')
  })
})

describe('formatSize', () => {
  it('should return dash for zero or negative size', () => {
    expect(formatSize(0, 100, 'token', 'BTCUSDT')).toBe('—')
    expect(formatSize(-1, 100, 'usdt', 'BTCUSDT')).toBe('—')
  })

  it('should format in token mode with symbol base', () => {
    expect(formatSize(1.5, 50000, 'token', 'BTCUSDT')).toBe('1.5000 BTC')
    expect(formatSize(13.06, 2200, 'token', 'ETHUSDT')).toBe('13.0600 ETH')
  })

  it('should strip USDC and PERP suffixes', () => {
    expect(formatSize(1, 100, 'token', 'SOLUSDC')).toBe('1.0000 SOL')
    expect(formatSize(1, 100, 'token', 'BTCPERP')).toBe('1.0000 BTC')
  })

  it('should format in usdt mode for small values', () => {
    // 10 * 50 = $500
    expect(formatSize(10, 50, 'usdt', 'SOLUSDT')).toBe('$500')
  })

  it('should format in usdt mode with k suffix', () => {
    // 1 * 50000 = $50000
    expect(formatSize(1, 50000, 'usdt', 'BTCUSDT')).toBe('$50.0k')
  })

  it('should format in usdt mode with M suffix', () => {
    // 100 * 50000 = $5,000,000
    expect(formatSize(100, 50000, 'usdt', 'BTCUSDT')).toBe('$5.00M')
  })

  it('should format with k for values between 1000 and 10000', () => {
    // 0.1 * 50000 = $5000
    expect(formatSize(0.1, 50000, 'usdt', 'BTCUSDT')).toBe('$5.00k')
  })

  it('should fall back to token format when price is 0 in usdt mode', () => {
    expect(formatSize(1.5, 0, 'usdt', 'BTCUSDT')).toBe('1.5000 BTC')
  })
})
