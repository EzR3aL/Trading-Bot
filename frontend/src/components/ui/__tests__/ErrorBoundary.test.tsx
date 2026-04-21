import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { useState } from 'react'

// Mock i18n config (ErrorBoundary uses i18n.t() directly, not useTranslation)
vi.mock('../../../i18n/config', () => ({
  default: {
    t: (key: string) => {
      const translations: Record<string, string> = {
        'common.errorBoundaryTitle': 'Something went wrong',
        'common.errorBoundaryGeneric': 'An unexpected error occurred.',
        'common.tryAgain': 'Try again',
        'common.goToDashboard': 'Go to Dashboard',
      }
      return translations[key] || key
    },
  },
}))

import ErrorBoundary from '../ErrorBoundary'

// Component that throws an error on demand
let shouldThrowGlobal = false

function ThrowingComponent() {
  if (shouldThrowGlobal) {
    throw new Error('Test error message')
  }
  return <div>Child content renders fine</div>
}

describe('ErrorBoundary', () => {
  beforeEach(() => {
    shouldThrowGlobal = false
    // Suppress React error boundary console errors in tests
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  it('should render children when no error occurs', () => {
    render(
      <ErrorBoundary>
        <ThrowingComponent />
      </ErrorBoundary>
    )

    expect(screen.getByText('Child content renders fine')).toBeInTheDocument()
  })

  it('should render default fallback when child throws', () => {
    shouldThrowGlobal = true

    render(
      <ErrorBoundary>
        <ThrowingComponent />
      </ErrorBoundary>
    )

    expect(screen.getByText('Something went wrong')).toBeInTheDocument()
    expect(screen.getByText('Test error message')).toBeInTheDocument()
    expect(screen.getByText('Try again')).toBeInTheDocument()
    expect(screen.getByText('Go to Dashboard')).toBeInTheDocument()
  })

  it('should render custom ReactNode fallback when provided', () => {
    shouldThrowGlobal = true
    const customFallback = <div>Custom error display</div>

    render(
      <ErrorBoundary fallback={customFallback}>
        <ThrowingComponent />
      </ErrorBoundary>
    )

    expect(screen.getByText('Custom error display')).toBeInTheDocument()
    expect(screen.queryByText('Something went wrong')).not.toBeInTheDocument()
  })

  it('should render custom render-fn fallback with error and reset', () => {
    shouldThrowGlobal = true

    render(
      <ErrorBoundary
        fallback={(err, reset) => (
          <div>
            <span>Render fn: {err.message}</span>
            <button onClick={reset}>Custom reset</button>
          </div>
        )}
      >
        <ThrowingComponent />
      </ErrorBoundary>
    )

    expect(screen.getByText('Render fn: Test error message')).toBeInTheDocument()

    shouldThrowGlobal = false
    fireEvent.click(screen.getByText('Custom reset'))

    expect(screen.getByText('Child content renders fine')).toBeInTheDocument()
  })

  it('should recover when Try again button is clicked and error is resolved', () => {
    shouldThrowGlobal = true

    render(
      <ErrorBoundary>
        <ThrowingComponent />
      </ErrorBoundary>
    )

    expect(screen.getByText('Something went wrong')).toBeInTheDocument()

    // Fix the error condition before clicking retry
    shouldThrowGlobal = false

    // Click "Try again" to reset error state - now the child will render without throwing
    fireEvent.click(screen.getByText('Try again'))

    expect(screen.getByText('Child content renders fine')).toBeInTheDocument()
  })

  it('should call onReset callback when Try again clicked', () => {
    shouldThrowGlobal = true
    const onReset = vi.fn()

    render(
      <ErrorBoundary onReset={onReset}>
        <ThrowingComponent />
      </ErrorBoundary>
    )

    shouldThrowGlobal = false
    fireEvent.click(screen.getByText('Try again'))

    expect(onReset).toHaveBeenCalledTimes(1)
  })

  it('should auto-reset when resetKeys change', () => {
    shouldThrowGlobal = true

    function Harness() {
      const [key, setKey] = useState('a')
      return (
        <div>
          <button onClick={() => setKey('b')}>change key</button>
          <ErrorBoundary resetKeys={[key]}>
            <ThrowingComponent />
          </ErrorBoundary>
        </div>
      )
    }

    render(<Harness />)

    expect(screen.getByText('Something went wrong')).toBeInTheDocument()

    // Fix the throwing condition, then change the reset key
    shouldThrowGlobal = false
    fireEvent.click(screen.getByText('change key'))

    expect(screen.getByText('Child content renders fine')).toBeInTheDocument()
    expect(screen.queryByText('Something went wrong')).not.toBeInTheDocument()
  })

  it('should display generic message when error has no message', () => {
    function ThrowsGenericError() {
      throw new Error()
    }

    render(
      <ErrorBoundary>
        <ThrowsGenericError />
      </ErrorBoundary>
    )

    expect(screen.getByText('Something went wrong')).toBeInTheDocument()
    expect(screen.getByText('An unexpected error occurred.')).toBeInTheDocument()
  })

  it('should call console.error via componentDidCatch', () => {
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    shouldThrowGlobal = true

    render(
      <ErrorBoundary>
        <ThrowingComponent />
      </ErrorBoundary>
    )

    // React and ErrorBoundary both call console.error
    expect(consoleSpy).toHaveBeenCalled()
  })

  it('should forward caught error to onError handler', () => {
    shouldThrowGlobal = true
    const onError = vi.fn()

    render(
      <ErrorBoundary onError={onError}>
        <ThrowingComponent />
      </ErrorBoundary>
    )

    expect(onError).toHaveBeenCalledTimes(1)
    const firstCall = onError.mock.calls[0]
    expect((firstCall[0] as Error).message).toBe('Test error message')
  })
})
