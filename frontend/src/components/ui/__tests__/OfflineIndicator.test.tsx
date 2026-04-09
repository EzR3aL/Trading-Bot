import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, act } from '@testing-library/react'
import OfflineIndicator from '../OfflineIndicator'

// Mock react-i18next
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, fallback: string) => fallback || key,
  }),
}))

describe('OfflineIndicator', () => {
  let originalOnLine: PropertyDescriptor | undefined

  beforeEach(() => {
    vi.useFakeTimers()
    originalOnLine = Object.getOwnPropertyDescriptor(navigator, 'onLine')
  })

  afterEach(() => {
    vi.useRealTimers()
    // Restore original navigator.onLine
    if (originalOnLine) {
      Object.defineProperty(navigator, 'onLine', originalOnLine)
    } else {
      Object.defineProperty(navigator, 'onLine', {
        value: true,
        configurable: true,
        writable: true,
      })
    }
  })

  it('should render nothing when online', () => {
    Object.defineProperty(navigator, 'onLine', {
      value: true,
      configurable: true,
    })

    const { container } = render(<OfflineIndicator />)

    expect(container.firstChild).toBeNull()
  })

  it('should show offline banner when navigator is offline', () => {
    Object.defineProperty(navigator, 'onLine', {
      value: false,
      configurable: true,
    })

    render(<OfflineIndicator />)

    expect(screen.getByRole('alert')).toBeInTheDocument()
    expect(screen.getByText('No internet connection')).toBeInTheDocument()
  })

  it('should have a dismiss button', () => {
    Object.defineProperty(navigator, 'onLine', {
      value: false,
      configurable: true,
    })

    render(<OfflineIndicator />)

    expect(screen.getByLabelText('Dismiss')).toBeInTheDocument()
  })

  it('should show banner when going offline via event', () => {
    Object.defineProperty(navigator, 'onLine', {
      value: true,
      configurable: true,
    })

    render(<OfflineIndicator />)

    // Initially nothing rendered
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()

    // Simulate going offline — wrap in act since it triggers state update
    act(() => {
      Object.defineProperty(navigator, 'onLine', {
        value: false,
        configurable: true,
      })
      window.dispatchEvent(new Event('offline'))
    })

    expect(screen.getByRole('alert')).toBeInTheDocument()
    expect(screen.getByText('No internet connection')).toBeInTheDocument()
  })
})
