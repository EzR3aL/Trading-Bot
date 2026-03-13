import { AxiosError } from 'axios'

/**
 * Extract a user-friendly error message from an API error.
 * Handles FastAPI 422 validation error arrays and plain string details.
 */
export function getApiErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof AxiosError) {
    const detail = error.response?.data?.detail
    if (typeof detail === 'string') return detail
    // FastAPI 422: detail is an array of {loc, msg, type}
    if (Array.isArray(detail) && detail.length > 0) {
      return detail
        .map((d: { loc?: string[]; msg?: string }) => {
          const field = d.loc?.filter(l => l !== 'body').join('.') || ''
          return field ? `${field}: ${d.msg}` : (d.msg || '')
        })
        .filter(Boolean)
        .join('; ') || fallback
    }
    return error.message || fallback
  }
  if (error instanceof Error) {
    return error.message || fallback
  }
  return fallback
}
