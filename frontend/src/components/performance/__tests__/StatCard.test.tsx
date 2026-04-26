import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import StatCard from '../StatCard'

describe('StatCard', () => {
  it('renders label and value', () => {
    render(<StatCard label="Win Rate" value="75%" />)
    expect(screen.getByText('Win Rate')).toBeInTheDocument()
    expect(screen.getByText('75%')).toBeInTheDocument()
  })

  it('applies custom color class to the value', () => {
    const { container } = render(<StatCard label="Best" value="$100" color="text-profit" />)
    const valueWrap = container.querySelector('.text-profit')
    expect(valueWrap).toBeTruthy()
  })

  it('shows ArrowUpRight when isPositive=true', () => {
    const { container } = render(<StatCard label="Best" value="+10" isPositive={true} />)
    const svgs = container.querySelectorAll('svg')
    expect(svgs.length).toBeGreaterThan(0)
  })

  it('shows ArrowDownRight when isPositive=false', () => {
    const { container } = render(<StatCard label="Worst" value="-10" isPositive={false} />)
    const svgs = container.querySelectorAll('svg')
    expect(svgs.length).toBeGreaterThan(0)
  })

  it('shows no arrow when isPositive is null/undefined', () => {
    const { container } = render(<StatCard label="Neutral" value="50" />)
    const svgs = container.querySelectorAll('svg')
    expect(svgs.length).toBe(0)
  })
})
