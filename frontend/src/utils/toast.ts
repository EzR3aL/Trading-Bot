/**
 * Unified toast API — single wrapper around the app's toast surface.
 *
 * Call sites should import from here rather than reaching into the store
 * directly. Centralises type/duration/theming so we can swap the
 * implementation (or tune defaults) in one place.
 *
 * The underlying surface is `useToastStore` (Zustand), rendered by
 * `ToastContainer` which is mounted once in `App.tsx`. We deliberately
 * did NOT add react-hot-toast / sonner / radix-toast — the existing
 * store already covers all four severities, dismiss, auto-timeout, and
 * max-stack behaviour.
 *
 * Do not import `useToastStore` in new code. Use these helpers.
 */
import { useToastStore, type ToastType } from '../stores/toastStore'

/** Default durations (ms) per severity. Errors linger a bit longer. */
const DEFAULT_DURATIONS: Record<ToastType, number> = {
  success: 5000,
  info: 5000,
  warning: 6000,
  error: 7000,
}

function show(type: ToastType, message: string, duration?: number): void {
  useToastStore.getState().addToast(type, message, duration ?? DEFAULT_DURATIONS[type])
}

/** Success toast (green). Auto-dismisses after 5s by default. */
export const showSuccess = (message: string, duration?: number): void =>
  show('success', message, duration)

/** Error toast (red). Auto-dismisses after 7s by default. */
export const showError = (message: string, duration?: number): void =>
  show('error', message, duration)

/** Info toast (blue). Auto-dismisses after 5s by default. */
export const showInfo = (message: string, duration?: number): void =>
  show('info', message, duration)

/** Warning toast (amber). Auto-dismisses after 6s by default. */
export const showWarning = (message: string, duration?: number): void =>
  show('warning', message, duration)
