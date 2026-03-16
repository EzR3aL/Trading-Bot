import { describe, it, expect } from 'vitest'
import { formatChartCurrency } from '../dateUtils'

describe('formatChartCurrency', () => {
  it('formats zero', () => {
    expect(formatChartCurrency(0)).toBe('$0')
  })

  it('formats small positive values', () => {
    expect(formatChartCurrency(45)).toBe('$45')
    expect(formatChartCurrency(999)).toBe('$999')
  })

  it('formats small negative values', () => {
    expect(formatChartCurrency(-600)).toBe('-$600')
    expect(formatChartCurrency(-50)).toBe('-$50')
  })

  it('formats thousands with K suffix', () => {
    expect(formatChartCurrency(1000)).toBe('$1K')
    expect(formatChartCurrency(1200)).toBe('$1.2K')
    expect(formatChartCurrency(2500)).toBe('$2.5K')
    expect(formatChartCurrency(10000)).toBe('$10K')
    expect(formatChartCurrency(999999)).toBe('$1000K')
    expect(formatChartCurrency(50000)).toBe('$50K')
  })

  it('formats negative thousands', () => {
    expect(formatChartCurrency(-1200)).toBe('-$1.2K')
    expect(formatChartCurrency(-5000)).toBe('-$5K')
  })

  it('formats millions with M suffix', () => {
    expect(formatChartCurrency(1000000)).toBe('$1.0M')
    expect(formatChartCurrency(2500000)).toBe('$2.5M')
  })

  it('formats negative millions', () => {
    expect(formatChartCurrency(-1500000)).toBe('-$1.5M')
  })

  it('handles NaN gracefully', () => {
    expect(formatChartCurrency(NaN)).toBe('$0')
    expect(formatChartCurrency(Infinity)).toBe('$0')
    expect(formatChartCurrency(-Infinity)).toBe('$0')
  })
})
