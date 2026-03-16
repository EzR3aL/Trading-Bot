/**
 * Centralized date/time formatting utilities.
 *
 * All timestamps from the API arrive as ISO 8601 strings in UTC.
 * These helpers convert them to the user's local browser timezone
 * so every displayed time reflects the user's own clock.
 *
 * This is important for tax compliance — trade open/close times must
 * be shown in the user's local timezone to match their jurisdiction.
 */

/** User's IANA timezone, e.g. "Europe/Berlin", "America/New_York" */
export const USER_TIMEZONE = Intl.DateTimeFormat().resolvedOptions().timeZone

/** Short timezone abbreviation, e.g. "CET", "EST" */
function getTimezoneAbbr(date: Date): string {
  const parts = new Intl.DateTimeFormat(undefined, { timeZoneName: 'short' }).formatToParts(date)
  return parts.find(p => p.type === 'timeZoneName')?.value ?? ''
}

/**
 * Full datetime: "09.03.2026, 14:30:21"
 * Uses the browser's locale and timezone automatically.
 */
export function formatDateTime(isoString: string | null | undefined): string {
  if (!isoString) return '--'
  const date = new Date(isoString)
  if (isNaN(date.getTime())) return '--'
  return date.toLocaleString()
}

/**
 * Date only: "09.03.2026" (German) or "3/9/2026" (US) etc.
 */
export function formatDate(isoString: string | null | undefined): string {
  if (!isoString) return '--'
  const date = new Date(isoString)
  if (isNaN(date.getTime())) return '--'
  return date.toLocaleDateString()
}

/**
 * Time only: "14:30" or "2:30 PM"
 */
export function formatTime(isoString: string | null | undefined): string {
  if (!isoString) return '--'
  const date = new Date(isoString)
  if (isNaN(date.getTime())) return '--'
  return date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
}

/**
 * Time with timezone label: "14:30 CET" or "2:30 PM EST"
 * Used in tooltips to make the timezone explicit for the user.
 */
export function formatTimeWithTz(isoString: string | null | undefined): string {
  if (!isoString) return '--'
  const date = new Date(isoString)
  if (isNaN(date.getTime())) return '--'
  const time = date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
  const tz = getTimezoneAbbr(date)
  return `${time} ${tz}`
}

/**
 * Short date for chart axis labels: "Jan 5", "Mär 9" etc.
 */
export function formatChartDate(isoString: string | null | undefined): string {
  if (!isoString) return ''
  const date = new Date(isoString)
  if (isNaN(date.getTime())) return ''
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

/**
 * Formatted date for the DatePicker display.
 * Uses browser locale (e.g. "09.03.2026" for de, "03/09/2026" for en-US).
 */
export function formatDatePickerDisplay(isoDateString: string): string {
  const date = new Date(isoDateString + 'T00:00:00')
  if (isNaN(date.getTime())) return ''
  return date.toLocaleDateString(undefined, { day: '2-digit', month: '2-digit', year: 'numeric' })
}

/**
 * Compact currency formatter for chart Y-axis labels.
 * $1200 → "$1.2K", $-600 → "-$600", $45 → "$45"
 */
export function formatChartCurrency(value: number): string {
  const abs = Math.abs(value)
  const sign = value < 0 ? '-' : ''
  if (abs >= 1_000_000) return `${sign}$${(abs / 1_000_000).toFixed(1)}M`
  if (abs >= 1_000) return `${sign}$${(abs / 1_000).toFixed(abs % 1_000 === 0 ? 0 : 1)}K`
  return `${sign}$${abs}`
}

/**
 * Localized month names based on browser locale.
 */
export function getLocalizedMonths(): string[] {
  const formatter = new Intl.DateTimeFormat(undefined, { month: 'long' })
  return Array.from({ length: 12 }, (_, i) =>
    formatter.format(new Date(2026, i, 1))
  )
}

/**
 * Localized short weekday names (Mon-Sun) based on browser locale.
 * Starts on Monday (ISO standard).
 */
export function getLocalizedWeekdays(): string[] {
  const formatter = new Intl.DateTimeFormat(undefined, { weekday: 'short' })
  // 2026-01-05 is a Monday
  return Array.from({ length: 7 }, (_, i) =>
    formatter.format(new Date(2026, 0, 5 + i))
  )
}
