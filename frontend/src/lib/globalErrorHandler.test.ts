import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import {
  installGlobalErrorHandler,
  __resetGlobalErrorHandlerForTests,
  GLOBAL_ERROR_TAG,
  DEDUPE_WINDOW_MS,
} from './globalErrorHandler'

/**
 * jsdom quirk: `PromiseRejectionEvent` is not a global constructor in older
 * jsdom releases. We dispatch a plain `Event('unhandledrejection')` and tack
 * on `reason`, which matches the shape the handler reads.
 */
function dispatchUnhandledRejection(target: Window, reason: unknown): void {
  const evt = new Event('unhandledrejection') as Event & { reason: unknown }
  evt.reason = reason
  target.dispatchEvent(evt)
}

function dispatchWindowError(
  target: Window,
  opts: { error?: unknown; message?: string; filename?: string; lineno?: number; colno?: number } = {},
): void {
  // jsdom supports ErrorEvent, but constructor args differ across versions —
  // build the event manually so tests are deterministic.
  const evt = new Event('error') as Event & {
    error?: unknown
    message?: string
    filename?: string
    lineno?: number
    colno?: number
  }
  evt.error = opts.error
  evt.message = opts.message ?? ''
  evt.filename = opts.filename ?? ''
  evt.lineno = opts.lineno ?? 0
  evt.colno = opts.colno ?? 0
  target.dispatchEvent(evt)
}

describe('installGlobalErrorHandler', () => {
  let consoleErrorSpy: ReturnType<typeof vi.spyOn>
  let consoleInfoSpy: ReturnType<typeof vi.spyOn>
  let consoleWarnSpy: ReturnType<typeof vi.spyOn>

  beforeEach(() => {
    __resetGlobalErrorHandlerForTests()
    consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    consoleInfoSpy = vi.spyOn(console, 'info').mockImplementation(() => {})
    consoleWarnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
  })

  afterEach(() => {
    __resetGlobalErrorHandlerForTests()
    consoleErrorSpy.mockRestore()
    consoleInfoSpy.mockRestore()
    consoleWarnSpy.mockRestore()
  })

  it('captures unhandled rejections and invokes toast + telemetry', () => {
    const toast = vi.fn()
    const reportError = vi.fn()

    installGlobalErrorHandler({ toast, reportError })

    const err = new Error('boom')
    dispatchUnhandledRejection(window, err)

    expect(toast).toHaveBeenCalledTimes(1)
    expect(toast).toHaveBeenCalledWith('boom')

    expect(reportError).toHaveBeenCalledTimes(1)
    const [reportedErr, reportedCtx] = reportError.mock.calls[0]
    expect(reportedErr).toBe(err)
    expect(reportedCtx.source).toBe('unhandledrejection')
    expect(reportedCtx.message).toBe('boom')
    expect(reportedCtx.stack).toBeTypeOf('string')
    expect(reportedCtx.timestamp).toBeTypeOf('number')

    expect(consoleErrorSpy).toHaveBeenCalledWith(
      GLOBAL_ERROR_TAG,
      expect.objectContaining({ source: 'unhandledrejection', message: 'boom' }),
      err,
    )
  })

  it('captures uncaught window errors with source metadata', () => {
    const toast = vi.fn()
    const reportError = vi.fn()

    installGlobalErrorHandler({ toast, reportError })

    const err = new TypeError('bad access')
    dispatchWindowError(window, {
      error: err,
      message: 'bad access',
      filename: 'app.js',
      lineno: 42,
      colno: 7,
    })

    expect(toast).toHaveBeenCalledWith('bad access')
    expect(reportError).toHaveBeenCalledTimes(1)
    const [, ctx] = reportError.mock.calls[0]
    expect(ctx.source).toBe('error')
    expect(ctx.filename).toBe('app.js')
    expect(ctx.lineno).toBe(42)
    expect(ctx.colno).toBe(7)
  })

  it('suppresses duplicate toasts within the 5s dedupe window', () => {
    const toast = vi.fn()
    const reportError = vi.fn()

    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-01-01T00:00:00Z'))

    installGlobalErrorHandler({ toast, reportError })

    dispatchUnhandledRejection(window, new Error('same'))
    vi.advanceTimersByTime(1000)
    dispatchUnhandledRejection(window, new Error('same'))
    vi.advanceTimersByTime(2000)
    dispatchUnhandledRejection(window, new Error('same'))

    expect(toast).toHaveBeenCalledTimes(1)
    expect(reportError).toHaveBeenCalledTimes(1)

    // Console.error still fires every time so devs see every occurrence.
    expect(consoleErrorSpy).toHaveBeenCalledTimes(3)

    // After the window elapses, the same message is allowed through again.
    vi.advanceTimersByTime(DEDUPE_WINDOW_MS + 100)
    dispatchUnhandledRejection(window, new Error('same'))

    expect(toast).toHaveBeenCalledTimes(2)
    expect(reportError).toHaveBeenCalledTimes(2)

    vi.useRealTimers()
  })

  it('does not suppress distinct messages', () => {
    const toast = vi.fn()
    const reportError = vi.fn()

    installGlobalErrorHandler({ toast, reportError, dedupeWindowMs: 60_000 })

    dispatchUnhandledRejection(window, new Error('first'))
    dispatchUnhandledRejection(window, new Error('second'))

    expect(toast).toHaveBeenCalledTimes(2)
    expect(toast).toHaveBeenNthCalledWith(1, 'first')
    expect(toast).toHaveBeenNthCalledWith(2, 'second')
  })

  it('normalizes non-Error rejection values', () => {
    const toast = vi.fn()
    const reportError = vi.fn()

    installGlobalErrorHandler({ toast, reportError })

    dispatchUnhandledRejection(window, 'plain string reason')
    dispatchUnhandledRejection(window, { code: 42 })
    dispatchUnhandledRejection(window, null)

    expect(toast).toHaveBeenNthCalledWith(1, 'plain string reason')
    expect(toast).toHaveBeenNthCalledWith(2, '{"code":42}')
    expect(toast).toHaveBeenNthCalledWith(3, 'Unknown error')
  })

  it('is idempotent: second install returns the same handle', () => {
    const toast = vi.fn()
    const first = installGlobalErrorHandler({ toast })
    const second = installGlobalErrorHandler({ toast })

    expect(second).toBe(first)

    dispatchUnhandledRejection(window, new Error('once'))
    // If the listener had been double-bound, toast would fire twice.
    expect(toast).toHaveBeenCalledTimes(1)
  })

  it('uninstall detaches both listeners', () => {
    const toast = vi.fn()
    const handle = installGlobalErrorHandler({ toast })
    handle.uninstall()

    // Pass a string rather than an Error — with no listener attached, jsdom
    // would otherwise surface an "Uncaught Exception" for the Error object.
    dispatchUnhandledRejection(window, 'should be ignored')
    dispatchWindowError(window, { message: 'also ignored' })

    expect(toast).not.toHaveBeenCalled()
  })

  it('does not let a throwing telemetry sink break the toast', () => {
    const toast = vi.fn()
    const reportError = vi.fn(() => {
      throw new Error('telemetry down')
    })

    installGlobalErrorHandler({ toast, reportError })

    dispatchUnhandledRejection(window, new Error('real failure'))

    expect(toast).toHaveBeenCalledWith('real failure')
    expect(consoleWarnSpy).toHaveBeenCalledWith(
      GLOBAL_ERROR_TAG,
      'telemetry sink threw',
      expect.any(Error),
    )
  })
})
