import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { DetailGrid } from '../DetailGrid'

describe('DetailGrid', () => {
  it('renders label and value for each item', () => {
    render(
      <DetailGrid
        items={[
          { label: 'Entry', value: '$100' },
          { label: 'Exit', value: '$110' },
        ]}
      />
    )
    expect(screen.getByText('Entry')).toBeDefined()
    expect(screen.getByText('$100')).toBeDefined()
    expect(screen.getByText('Exit')).toBeDefined()
    expect(screen.getByText('$110')).toBeDefined()
  })

  it('hides items with hidden=true', () => {
    render(
      <DetailGrid
        items={[
          { label: 'Visible', value: 'yes' },
          { label: 'Hidden', value: 'no', hidden: true },
        ]}
      />
    )
    expect(screen.getByText('Visible')).toBeDefined()
    expect(screen.queryByText('Hidden')).toBeNull()
  })

  it('applies col-span-2 when specified', () => {
    const { container } = render(
      <DetailGrid
        items={[
          { label: 'Wide', value: 'full width', colSpan: 2 },
        ]}
      />
    )
    const wideItem = container.querySelector('.col-span-2')
    expect(wideItem).toBeDefined()
  })

  it('renders empty grid when no items', () => {
    const { container } = render(<DetailGrid items={[]} />)
    const grid = container.querySelector('.grid')
    expect(grid?.children.length).toBe(0)
  })

  it('renders React nodes as values', () => {
    render(
      <DetailGrid
        items={[
          { label: 'Custom', value: <span data-testid="custom">Node</span> },
        ]}
      />
    )
    expect(screen.getByTestId('custom')).toBeDefined()
  })
})
