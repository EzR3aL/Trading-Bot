import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
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
  })

  it('should render custom fallback when provided', () => {
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
})
