import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import Pagination from '../Pagination'

describe('Pagination', () => {
  const defaultProps = {
    page: 1,
    totalPages: 5,
    onPageChange: vi.fn(),
  }

  it('should render nothing when totalPages is 1', () => {
    const { container } = render(
      <Pagination page={1} totalPages={1} onPageChange={vi.fn()} />
    )
    expect(container.firstChild).toBeNull()
  })

  it('should render nothing when totalPages is 0', () => {
    const { container } = render(
      <Pagination page={1} totalPages={0} onPageChange={vi.fn()} />
    )
    expect(container.firstChild).toBeNull()
  })

  it('should render page buttons for small page count', () => {
    render(<Pagination {...defaultProps} totalPages={5} />)

    // Should show page numbers 1-5
    for (let i = 1; i <= 5; i++) {
      expect(screen.getByText(String(i))).toBeInTheDocument()
    }
  })

  it('should render previous and next navigation buttons', () => {
    render(<Pagination {...defaultProps} />)

    expect(screen.getByLabelText('Previous page')).toBeInTheDocument()
    expect(screen.getByLabelText('Next page')).toBeInTheDocument()
  })

  it('should disable previous button on first page', () => {
    render(<Pagination {...defaultProps} page={1} />)

    expect(screen.getByLabelText('Previous page')).toBeDisabled()
  })

  it('should disable next button on last page', () => {
    render(<Pagination {...defaultProps} page={5} totalPages={5} />)

    expect(screen.getByLabelText('Next page')).toBeDisabled()
  })

  it('should call onPageChange when clicking a page number', () => {
    const onPageChange = vi.fn()
    render(<Pagination {...defaultProps} onPageChange={onPageChange} />)

    fireEvent.click(screen.getByText('3'))
    expect(onPageChange).toHaveBeenCalledWith(3)
  })

  it('should call onPageChange when clicking next button', () => {
    const onPageChange = vi.fn()
    render(<Pagination page={2} totalPages={5} onPageChange={onPageChange} />)

    fireEvent.click(screen.getByLabelText('Next page'))
    expect(onPageChange).toHaveBeenCalledWith(3)
  })

  it('should call onPageChange when clicking previous button', () => {
    const onPageChange = vi.fn()
    render(<Pagination page={3} totalPages={5} onPageChange={onPageChange} />)

    fireEvent.click(screen.getByLabelText('Previous page'))
    expect(onPageChange).toHaveBeenCalledWith(2)
  })

  it('should not go below page 1 with the previous button', () => {
    const onPageChange = vi.fn()
    render(<Pagination page={1} totalPages={5} onPageChange={onPageChange} />)

    // Previous button should be disabled on page 1
    const prevButton = screen.getByLabelText('Previous page')
    expect(prevButton).toBeDisabled()
    // Disabled button should not fire onPageChange
  })

  it('should show ellipsis for large page counts', () => {
    render(<Pagination page={5} totalPages={20} onPageChange={vi.fn()} />)

    // Should show ellipsis
    const ellipses = screen.getAllByText('...')
    expect(ellipses.length).toBeGreaterThanOrEqual(1)
  })

  it('should show all pages when totalPages <= 7', () => {
    render(<Pagination page={4} totalPages={7} onPageChange={vi.fn()} />)

    for (let i = 1; i <= 7; i++) {
      expect(screen.getByText(String(i))).toBeInTheDocument()
    }
    expect(screen.queryByText('...')).not.toBeInTheDocument()
  })

  it('should render optional label', () => {
    render(<Pagination {...defaultProps} label="Seite 1 von 5" />)

    expect(screen.getByText('Seite 1 von 5')).toBeInTheDocument()
  })

  it('should not render label when not provided', () => {
    render(<Pagination {...defaultProps} />)

    expect(screen.queryByText(/Seite/)).not.toBeInTheDocument()
  })
})
