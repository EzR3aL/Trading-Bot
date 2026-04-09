import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import FilterDropdown from '../FilterDropdown'

// Mock themeStore
vi.mock('../../../stores/themeStore', () => ({
  useThemeStore: () => 'dark',
}))

const options = [
  { value: 'all', label: 'All' },
  { value: 'open', label: 'Open' },
  { value: 'closed', label: 'Closed' },
]

describe('FilterDropdown', () => {
  it('should render with selected value label', () => {
    render(<FilterDropdown value="open" onChange={vi.fn()} options={options} />)

    expect(screen.getByText('Open')).toBeInTheDocument()
  })

  it('should not show dropdown list initially', () => {
    render(<FilterDropdown value="all" onChange={vi.fn()} options={options} />)

    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it('should open dropdown on button click', () => {
    render(<FilterDropdown value="all" onChange={vi.fn()} options={options} />)

    const button = screen.getByRole('button', { expanded: false })
    fireEvent.click(button)

    expect(screen.getByRole('listbox')).toBeInTheDocument()
  })

  it('should show all options when open', () => {
    render(<FilterDropdown value="all" onChange={vi.fn()} options={options} />)

    fireEvent.click(screen.getByText('All'))

    expect(screen.getAllByRole('option')).toHaveLength(3)
    expect(screen.getByText('Open')).toBeInTheDocument()
    expect(screen.getByText('Closed')).toBeInTheDocument()
  })

  it('should call onChange and close when an option is selected', () => {
    const onChange = vi.fn()
    render(<FilterDropdown value="all" onChange={onChange} options={options} />)

    // Open dropdown
    fireEvent.click(screen.getByText('All'))

    // Select an option
    fireEvent.click(screen.getByText('Closed'))

    expect(onChange).toHaveBeenCalledWith('closed')
    // Dropdown should close after selection
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it('should mark selected option with aria-selected', () => {
    render(<FilterDropdown value="open" onChange={vi.fn()} options={options} />)

    // Open dropdown
    fireEvent.click(screen.getByText('Open'))

    const selectedOption = screen.getByRole('option', { selected: true })
    expect(selectedOption).toHaveTextContent('Open')
  })

  it('should set aria-expanded correctly', () => {
    render(<FilterDropdown value="all" onChange={vi.fn()} options={options} ariaLabel="Filter" />)

    const button = screen.getByLabelText('Filter')
    expect(button).toHaveAttribute('aria-expanded', 'false')

    fireEvent.click(button)
    expect(button).toHaveAttribute('aria-expanded', 'true')
  })

  it('should have aria-haspopup attribute', () => {
    render(<FilterDropdown value="all" onChange={vi.fn()} options={options} ariaLabel="Filter" />)

    const button = screen.getByLabelText('Filter')
    expect(button).toHaveAttribute('aria-haspopup', 'listbox')
  })
})
