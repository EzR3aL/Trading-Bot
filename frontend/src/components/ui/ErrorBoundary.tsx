import { Component, type ErrorInfo, type ReactNode } from 'react'
import i18n from '../../i18n/config'

type FallbackRender = (error: Error, reset: () => void) => ReactNode

interface Props {
  children: ReactNode
  fallback?: ReactNode | FallbackRender
  onReset?: () => void
  onError?: (error: Error, info: ErrorInfo) => void
  resetKeys?: unknown[]
}

interface State {
  hasError: boolean
  error: Error | null
}

function keysChanged(prev: unknown[] | undefined, next: unknown[] | undefined): boolean {
  if (!prev || !next) return prev !== next
  if (prev.length !== next.length) return true
  for (let i = 0; i < prev.length; i++) {
    if (!Object.is(prev[i], next[i])) return true
  }
  return false
}

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null }
  private retryCount = 0

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    if (import.meta.env.DEV) {
      console.error('ErrorBoundary caught:', error, info.componentStack)
    }
    this.props.onError?.(error, info)

    // Auto-recover from DOM manipulation errors (caused by browser extensions
    // or concurrent DOM modifications during session expiry redirects)
    const isDomError = error.message?.includes('removeChild') ||
                       error.message?.includes('insertBefore') ||
                       error.message?.includes('not a child')
    if (isDomError && this.retryCount < 3) {
      this.retryCount++
      this.setState({ hasError: false, error: null })
    }
  }

  componentDidUpdate(prevProps: Props) {
    // Auto-reset when resetKeys change (e.g. route change via location.pathname)
    if (this.state.hasError && keysChanged(prevProps.resetKeys, this.props.resetKeys)) {
      this.handleReset()
    }
  }

  handleReset = () => {
    this.retryCount = 0
    this.props.onReset?.()
    this.setState({ hasError: false, error: null })
  }

  renderFallback(error: Error): ReactNode {
    const { fallback } = this.props
    if (typeof fallback === 'function') {
      return (fallback as FallbackRender)(error, this.handleReset)
    }
    if (fallback !== undefined) return fallback

    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] p-8">
        <div className="bg-[#1a1a2e] border border-red-500/30 rounded-xl p-8 max-w-md text-center">
          <h2 className="text-xl font-bold text-red-400 mb-3">
            {i18n.t('common.errorBoundaryTitle')}
          </h2>
          <p className="text-gray-400 mb-4 text-sm">
            {error?.message || i18n.t('common.errorBoundaryGeneric')}
          </p>
          <div className="flex flex-wrap gap-3 justify-center">
            <button
              type="button"
              onClick={this.handleReset}
              className="px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg transition-colors"
            >
              {i18n.t('common.tryAgain')}
            </button>
            <a
              href="/"
              className="px-4 py-2 bg-white/5 hover:bg-white/10 border border-white/10 text-white rounded-lg transition-colors"
            >
              {i18n.t('common.goToDashboard')}
            </a>
          </div>
        </div>
      </div>
    )
  }

  render() {
    if (this.state.hasError && this.state.error) {
      return this.renderFallback(this.state.error)
    }
    return this.props.children
  }
}
