import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'
import ToastContainer from '../Toast'
import { useToastStore } from '../../../stores/toastStore'

describe('ToastContainer', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    useToastStore.setState({ toasts: [] })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('should render empty container when no toasts', () => {
    const { container } = render(<ToastContainer />)
    // Container exists but has no toast items
    const toastContainer = container.firstChild as HTMLElement
    expect(toastContainer).toBeTruthy()
    expect(toastContainer.children).toHaveLength(0)
  })

  it('should render toast items from store', () => {
    useToastStore.setState({
      toasts: [
        { id: 'toast-1', type: 'success', message: 'All good!', duration: 5000 },
        { id: 'toast-2', type: 'error', message: 'Something broke', duration: 5000 },
      ],
    })

    render(<ToastContainer />)

    expect(screen.getByText('All good!')).toBeInTheDocument()
    expect(screen.getByText('Something broke')).toBeInTheDocument()
  })

  it('should render toast with correct role="alert"', () => {
    useToastStore.setState({
      toasts: [
        { id: 'toast-1', type: 'info', message: 'Notice', duration: 5000 },
      ],
    })

    render(<ToastContainer />)

    expect(screen.getByRole('alert')).toBeInTheDocument()
  })

  it('should have dismiss button for each toast', () => {
    useToastStore.setState({
      toasts: [
        { id: 'toast-1', type: 'warning', message: 'Warning!', duration: 5000 },
      ],
    })

    render(<ToastContainer />)

    expect(screen.getByLabelText('Dismiss notification')).toBeInTheDocument()
  })

  it('should remove toast when dismiss is clicked', () => {
    useToastStore.setState({
      toasts: [
        { id: 'toast-1', type: 'success', message: 'Dismiss me', duration: 5000 },
      ],
    })

    render(<ToastContainer />)

    const dismissButton = screen.getByLabelText('Dismiss notification')
    fireEvent.click(dismissButton)

    // The exit animation waits 300ms before removing
    act(() => {
      vi.advanceTimersByTime(300)
    })

    expect(useToastStore.getState().toasts).toHaveLength(0)
  })

  it('should render links in toast messages', () => {
    useToastStore.setState({
      toasts: [
        {
          id: 'toast-1',
          type: 'info',
          message: 'Visit https://example.com for details',
          duration: 5000,
        },
      ],
    })

    render(<ToastContainer />)

    const link = screen.getByText('https://example.com')
    expect(link.tagName).toBe('A')
    expect(link).toHaveAttribute('href', 'https://example.com')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
  })

  it('should render multiline messages', () => {
    useToastStore.setState({
      toasts: [
        {
          id: 'toast-1',
          type: 'error',
          message: 'Line one\nLine two',
          duration: 5000,
        },
      ],
    })

    render(<ToastContainer />)

    expect(screen.getByText('Line one')).toBeInTheDocument()
    expect(screen.getByText('Line two')).toBeInTheDocument()
  })
})
