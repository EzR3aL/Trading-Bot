import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import DatePicker from '../DatePicker'

// Mock themeStore
vi.mock('../../../stores/themeStore', () => ({
  useThemeStore: () => 'dark',
}))

// Mock dateUtils
vi.mock('../../../utils/dateUtils', () => ({
  formatDatePickerDisplay: (val: string) => val,
  getLocalizedMonths: () => [
    'January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December',
  ],
  getLocalizedWeekdays: () => ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su'],
}))

describe('DatePicker', () => {
  it('should render the toggle button', () => {
    render(<DatePicker value="" onChange={vi.fn()} label="Start" />)

    expect(screen.getByLabelText('Start')).toBeInTheDocument()
  })

  it('should show placeholder text when no value', () => {
    render(<DatePicker value="" onChange={vi.fn()} placeholder="Pick a date" />)

    expect(screen.getByText('Pick a date')).toBeInTheDocument()
  })

  it('should show calendar when button is clicked', () => {
    render(<DatePicker value="" onChange={vi.fn()} label="Date" />)

    fireEvent.click(screen.getByLabelText('Date'))

    // Should show month navigation buttons
    expect(screen.getByLabelText('Previous month')).toBeInTheDocument()
    expect(screen.getByLabelText('Next month')).toBeInTheDocument()
  })

  it('should show weekday headers when open', () => {
    render(<DatePicker value="" onChange={vi.fn()} label="Date" />)

    fireEvent.click(screen.getByLabelText('Date'))

    expect(screen.getByText('Mo')).toBeInTheDocument()
    expect(screen.getByText('Su')).toBeInTheDocument()
  })

  it('should call onChange with selected date and close', () => {
    const onChange = vi.fn()
    // Use a fixed date so we can predict which day buttons appear
    render(<DatePicker value="2026-04-01" onChange={onChange} label="Date" />)

    fireEvent.click(screen.getByLabelText('Date'))

    // Click day 15
    const day15 = screen.getByRole('button', { name: '15' })
    fireEvent.click(day15)

    expect(onChange).toHaveBeenCalledWith('2026-04-15')
  })

  it('should navigate to previous month', () => {
    render(<DatePicker value="2026-04-01" onChange={vi.fn()} label="Date" />)

    fireEvent.click(screen.getByLabelText('Date'))
    expect(screen.getByText('April 2026')).toBeInTheDocument()

    fireEvent.click(screen.getByLabelText('Previous month'))
    expect(screen.getByText('March 2026')).toBeInTheDocument()
  })

  it('should navigate to next month', () => {
    render(<DatePicker value="2026-04-01" onChange={vi.fn()} label="Date" />)

    fireEvent.click(screen.getByLabelText('Date'))
    expect(screen.getByText('April 2026')).toBeInTheDocument()

    fireEvent.click(screen.getByLabelText('Next month'))
    expect(screen.getByText('May 2026')).toBeInTheDocument()
  })

  it('should clear value when clear button is clicked', () => {
    const onChange = vi.fn()
    render(<DatePicker value="2026-04-15" onChange={onChange} label="Date" />)

    fireEvent.click(screen.getByLabelText('Date'))

    // Click the clear button (Löschen)
    fireEvent.click(screen.getByText('Löschen'))

    expect(onChange).toHaveBeenCalledWith('')
  })

  it('should show "Heute" button to select today', () => {
    const onChange = vi.fn()
    render(<DatePicker value="" onChange={onChange} label="Date" />)

    fireEvent.click(screen.getByLabelText('Date'))

    expect(screen.getByText('Heute')).toBeInTheDocument()
  })

  it('should set aria-expanded correctly', () => {
    render(<DatePicker value="" onChange={vi.fn()} label="Date" />)

    const button = screen.getByLabelText('Date')
    expect(button).toHaveAttribute('aria-expanded', 'false')

    fireEvent.click(button)
    expect(button).toHaveAttribute('aria-expanded', 'true')
  })
})
