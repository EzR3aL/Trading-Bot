/**
 * Global error handler — top-level browser hooks for async failures.
 *
 * Issue #331. Before this module, an unhandled Promise rejection (e.g. a
 * `fetch(...).then(...)` with no `.catch`, or a missing `await`) disappeared
 * silently: DevTools logged it, but the user got no feedback and telemetry
 * never fired.
 *
 * `installGlobalErrorHandler()` attaches two window listeners:
 *   - `unhandledrejection` — unhandled Promise rejections
 *   - `error`              — uncaught errors (incl. errors thrown inside
 *                            async event handlers where no ErrorBoundary
 *                            is in the React tree above the throw)
 *
 * For each event we:
 *   1. Log a structured record to `console.error` tagged `[GlobalError]`.
 *   2. Forward to a pluggable `reportError` telemetry hook (stub: emits
 *      `[telemetry]` on `console.info`; later wires to Sentry/PostHog).
 *   3. Show a user-visible toast via the app's unified toast helper.
 *   4. De-dupe bursts: the same normalized message within 5 s produces
 *      exactly one toast and one telemetry call.
 *
 * Dependencies are injected via `options` so tests can assert behaviour
 * without monkey-patching globals.
 */
import { showError } from '../utils/toast'

export const GLOBAL_ERROR_TAG = '[GlobalError]'
export const TELEMETRY_TAG = '[telemetry]'
export const DEDUPE_WINDOW_MS = 5000

export type ErrorSource = 'unhandledrejection' | 'error'

export interface ErrorContext {
  source: ErrorSource
  message: string
  stack?: string
  filename?: string
  lineno?: number
  colno?: number
  timestamp: number
}

export type ReportErrorFn = (err: unknown, ctx: ErrorContext) => void
export type ToastFn = (message: string) => void

export interface InstallOptions {
  /** Telemetry sink. Defaults to a console-based stub. */
  reportError?: ReportErrorFn
  /** User-visible toast. Defaults to the app's `showError` helper. */
  toast?: ToastFn
  /** Override dedupe window (ms). Defaults to 5000. */
  dedupeWindowMs?: number
  /** Window target (for tests). Defaults to global `window`. */
  target?: Window
}

export interface InstalledHandler {
  /** Remove both listeners. Safe to call multiple times. */
  uninstall: () => void
}

/**
 * Default telemetry sink — a console stub. Swap this out once Sentry/PostHog
 * is wired. The structured record mirrors what a real SDK would capture.
 */
function defaultReportError(err: unknown, ctx: ErrorContext): void {
  // eslint-disable-next-line no-console
  console.info(TELEMETRY_TAG, {
    source: ctx.source,
    message: ctx.message,
    stack: ctx.stack,
    filename: ctx.filename,
    lineno: ctx.lineno,
    colno: ctx.colno,
    timestamp: ctx.timestamp,
    // Preserve the raw value for debugging (may be a non-Error thrown value).
    error: err,
  })
}

/**
 * Degrade gracefully if no toast surface is available. Not expected in the
 * real app (toast store ships with the SPA), but guards isolated entrypoints
 * (Storybook, server-render probes, etc.).
 */
function defaultToast(message: string): void {
  try {
    showError(message)
  } catch {
    // TODO(#331): integrate with alternate toast surface if showError fails
    // (e.g. store not initialised during a very early boot error).
    // eslint-disable-next-line no-console
    console.warn(GLOBAL_ERROR_TAG, 'toast unavailable, message:', message)
  }
}

function normalizeMessage(value: unknown): string {
  if (value instanceof Error) {
    return value.message || value.name || 'Unknown error'
  }
  if (typeof value === 'string') return value
  if (value === null || value === undefined) return 'Unknown error'
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

function extractStack(value: unknown): string | undefined {
  if (value instanceof Error && typeof value.stack === 'string') {
    return value.stack
  }
  return undefined
}

let installed: InstalledHandler | null = null

/**
 * Attach `unhandledrejection` + `error` listeners on `window`.
 *
 * Idempotent: calling twice returns the same handle and does not double-bind.
 * Call once from the app entrypoint (`main.tsx`) before `createRoot(...)`.
 */
export function installGlobalErrorHandler(
  options: InstallOptions = {},
): InstalledHandler {
  if (installed) return installed

  const target = options.target ?? (typeof window !== 'undefined' ? window : undefined)
  if (!target) {
    // SSR / non-browser environment — nothing to attach to.
    const noop: InstalledHandler = { uninstall: () => {} }
    return noop
  }

  const report = options.reportError ?? defaultReportError
  const toast = options.toast ?? defaultToast
  const dedupeWindow = options.dedupeWindowMs ?? DEDUPE_WINDOW_MS

  const lastSeen = new Map<string, number>()

  function shouldSuppress(message: string, now: number): boolean {
    const previous = lastSeen.get(message)
    lastSeen.set(message, now)
    if (previous === undefined) return false
    return now - previous < dedupeWindow
  }

  function handle(source: ErrorSource, rawError: unknown, extra: Partial<ErrorContext> = {}): void {
    const message = normalizeMessage(rawError)
    const now = Date.now()
    const ctx: ErrorContext = {
      source,
      message,
      stack: extractStack(rawError),
      timestamp: now,
      ...extra,
    }

    // Always log for developers, even when the toast is suppressed.
    // eslint-disable-next-line no-console
    console.error(GLOBAL_ERROR_TAG, ctx, rawError)

    if (shouldSuppress(message, now)) return

    try {
      report(rawError, ctx)
    } catch (telemetryErr) {
      // eslint-disable-next-line no-console
      console.warn(GLOBAL_ERROR_TAG, 'telemetry sink threw', telemetryErr)
    }

    try {
      toast(message)
    } catch (toastErr) {
      // eslint-disable-next-line no-console
      console.warn(GLOBAL_ERROR_TAG, 'toast sink threw', toastErr)
    }
  }

  const onRejection = (event: PromiseRejectionEvent): void => {
    handle('unhandledrejection', event.reason)
  }

  const onError = (event: ErrorEvent): void => {
    // `error` can be null when the event is synthetic; fall back to message.
    const payload = event.error ?? event.message ?? 'Unknown error'
    handle('error', payload, {
      filename: event.filename,
      lineno: event.lineno,
      colno: event.colno,
    })
  }

  target.addEventListener('unhandledrejection', onRejection as EventListener)
  target.addEventListener('error', onError as EventListener)

  installed = {
    uninstall: () => {
      target.removeEventListener('unhandledrejection', onRejection as EventListener)
      target.removeEventListener('error', onError as EventListener)
      lastSeen.clear()
      installed = null
    },
  }

  return installed
}

/**
 * Test-only: reset the install guard. Not exported from the barrel; use
 * `uninstall()` on the returned handle in app code.
 */
export function __resetGlobalErrorHandlerForTests(): void {
  if (installed) installed.uninstall()
  installed = null
}
