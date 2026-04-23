/**
 * Locale-aware number formatting helpers.
 *
 * These utilities centralise the common cases scattered across
 * `toFixed()`/`toLocaleString()` call sites so future tweaks
 * (grouping, min/max digits, currency symbol position) happen
 * in one place. Uses the browser's resolved locale by default.
 *
 * Not a wholesale migration — existing `toFixed` sites keep working.
 * New code and any touched components should prefer these helpers.
 */

/**
 * Format a USD amount, e.g. `1234.5` → `$1,234.50`.
 * Accepts `null`/`undefined` for missing values and returns a dash.
 */
export function formatCurrency(
  value: number | null | undefined,
  { decimals = 2, withSign = false }: { decimals?: number; withSign?: boolean } = {}
): string {
  if (value == null || !Number.isFinite(value)) return '--'
  const sign = withSign && value > 0 ? '+' : ''
  const formatted = new Intl.NumberFormat(undefined, {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(value)
  return `${sign}${formatted}`
}

/**
 * Format a percent value. Input is the raw percent (e.g. `12.34`, not `0.1234`).
 * `formatPercent(12.34)` → `+12.34%`, `formatPercent(-5)` → `-5.00%`.
 */
export function formatPercent(
  value: number | null | undefined,
  { decimals = 2, withSign = true }: { decimals?: number; withSign?: boolean } = {}
): string {
  if (value == null || !Number.isFinite(value)) return '--'
  const sign = withSign && value > 0 ? '+' : ''
  const formatted = new Intl.NumberFormat(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(value)
  return `${sign}${formatted}%`
}

/**
 * Plain number with locale-aware grouping, e.g. `1234567` → `1,234,567`.
 */
export function formatNumber(
  value: number | null | undefined,
  { decimals = 0 }: { decimals?: number } = {}
): string {
  if (value == null || !Number.isFinite(value)) return '--'
  return new Intl.NumberFormat(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(value)
}
