import { AxiosError } from 'axios'
import { getApiErrorMessage } from '../api-error'

// Helper to create a mock AxiosError with response data
function makeAxiosError(data: unknown, status = 400): AxiosError {
  const error = new AxiosError('Request failed')
  error.response = {
    data,
    status,
    statusText: 'Bad Request',
    headers: {},
    config: {} as never,
  }
  return error
}

describe('getApiErrorMessage', () => {
  const fallback = 'Something went wrong'

  it('extracts plain string detail from AxiosError', () => {
    const error = makeAxiosError({ detail: 'Invalid credentials' })
    expect(getApiErrorMessage(error, fallback)).toBe('Invalid credentials')
  })

  it('extracts message from object detail', () => {
    const error = makeAxiosError({ detail: { message: 'Token expired', type: 'auth' } })
    expect(getApiErrorMessage(error, fallback)).toBe('Token expired')
  })

  it('extracts error messages from 422 validation error array', () => {
    const error = makeAxiosError(
      {
        detail: [
          { loc: ['body', 'username'], msg: 'field required', type: 'value_error' },
          { loc: ['body', 'password'], msg: 'too short', type: 'value_error' },
        ],
      },
      422,
    )
    const msg = getApiErrorMessage(error, fallback)
    expect(msg).toContain('username: field required')
    expect(msg).toContain('password: too short')
  })

  it('filters out "body" from loc path in 422 errors', () => {
    const error = makeAxiosError(
      { detail: [{ loc: ['body', 'email'], msg: 'invalid format', type: 'value_error' }] },
      422,
    )
    const msg = getApiErrorMessage(error, fallback)
    expect(msg).toBe('email: invalid format')
    expect(msg).not.toContain('body')
  })

  it('handles 422 entry without loc field', () => {
    const error = makeAxiosError(
      { detail: [{ msg: 'general error', type: 'value_error' }] },
      422,
    )
    expect(getApiErrorMessage(error, fallback)).toBe('general error')
  })

  it('falls back to AxiosError.message when detail is missing', () => {
    const error = new AxiosError('Network Error')
    error.response = undefined
    expect(getApiErrorMessage(error, fallback)).toBe('Network Error')
  })

  it('falls back to AxiosError.message for empty validation detail array', () => {
    const error = makeAxiosError({ detail: [] }, 422)
    // Empty array produces empty joined string, which is falsy, so fallback is used
    // But the || fallback only applies to the .join result; the code returns error.message
    expect(getApiErrorMessage(error, fallback)).toBe('Request failed')
  })

  it('handles plain Error instances', () => {
    const error = new Error('Something broke')
    expect(getApiErrorMessage(error, fallback)).toBe('Something broke')
  })

  it('returns fallback for unknown error types', () => {
    expect(getApiErrorMessage('string error', fallback)).toBe(fallback)
    expect(getApiErrorMessage(42, fallback)).toBe(fallback)
    expect(getApiErrorMessage(null, fallback)).toBe(fallback)
    expect(getApiErrorMessage(undefined, fallback)).toBe(fallback)
  })
})
