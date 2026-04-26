import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import Sparkline from '../Sparkline'

describe('Sparkline', () => {
  it('renders a placeholder div when fewer than 2 points', () => {
    const { container } = render(<Sparkline data={[1]} color="#0f0" width={100} height={20} />)
    expect(container.querySelector('svg')).toBeNull()
    const div = container.firstChild as HTMLElement
    expect(div.style.width).toBe('100px')
    expect(div.style.height).toBe('20px')
  })

  it('renders an SVG with polyline + polygon when given enough points', () => {
    const { container } = render(<Sparkline data={[1, 2, 3, 4]} color="#00ff00" />)
    const svg = container.querySelector('svg')
    expect(svg).toBeTruthy()
    expect(container.querySelector('polyline')).toBeTruthy()
    expect(container.querySelector('polygon')).toBeTruthy()
  })

  it('uses the provided width/height as the viewBox', () => {
    const { container } = render(<Sparkline data={[1, 2, 3]} color="#fff" width={120} height={40} />)
    const svg = container.querySelector('svg')!
    expect(svg.getAttribute('viewBox')).toBe('0 0 120 40')
  })

  it('handles flat data without divide-by-zero', () => {
    const { container } = render(<Sparkline data={[5, 5, 5, 5]} color="#abc" />)
    expect(container.querySelector('polyline')).toBeTruthy()
  })
})
