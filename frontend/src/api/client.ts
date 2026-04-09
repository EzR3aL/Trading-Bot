import axios from 'axios'
import i18n from '../i18n/config'

const api = axios.create({
  baseURL: '/api',
  headers: { 'Content-Type': 'application/json' },
  timeout: 15_000,
  withCredentials: true, // Sends httpOnly cookies with every request
})

// Refresh lock to prevent multiple simultaneous refresh attempts
let isRefreshing = false
let refreshSubscribers: (() => void)[] = []
let refreshRetryCount = 0
const MAX_REFRESH_RETRIES = 3

// Token expiry timestamp (ms) — persisted to localStorage so it survives PWA kills
const TOKEN_EXPIRY_KEY = 'token_expiry_ms'

function loadTokenExpiry(): number | null {
  try {
    const stored = localStorage.getItem(TOKEN_EXPIRY_KEY)
    if (!stored) return null
    const val = Number(stored)
    return Number.isFinite(val) ? val : null
  } catch {
    return null
  }
}

function persistTokenExpiry(ms: number | null) {
  try {
    if (ms !== null) {
      localStorage.setItem(TOKEN_EXPIRY_KEY, String(ms))
    } else {
      localStorage.removeItem(TOKEN_EXPIRY_KEY)
    }
  } catch {
    // localStorage unavailable (private browsing, storage full) — non-critical
  }
}

let tokenExpiryMs: number | null = loadTokenExpiry()

// Proactive refresh: refresh token 5 minutes before expiry
let proactiveRefreshTimer: ReturnType<typeof setTimeout> | null = null

function subscribeTokenRefresh(cb: () => void) {
  refreshSubscribers.push(cb)
}

function onTokenRefreshed() {
  refreshSubscribers.forEach((cb) => cb())
  refreshSubscribers = []
}

function onRefreshFailed() {
  refreshSubscribers = []
}

let sessionExpiring = false

function handleSessionExpiry() {
  // Guard: prevent multiple calls from concurrent 401 responses
  if (sessionExpiring) return
  // Don't redirect if already on login page (prevents infinite loop)
  if (window.location.pathname === '/login') return
  sessionExpiring = true

  tokenExpiryMs = null
  persistTokenExpiry(null)
  clearProactiveRefresh()

  // Show a brief message before redirect — use existing element or create one
  let msg = document.getElementById('session-expiry-msg')
  if (!msg) {
    msg = document.createElement('div')
    msg.id = 'session-expiry-msg'
    msg.textContent = i18n.t('common.sessionExpired', 'Session expired. Redirecting to login...')
    msg.style.cssText = `
      position: fixed; top: 20px; left: 50%; transform: translateX(-50%);
      padding: 12px 24px; background: rgba(239,68,68,0.9); color: white;
      border-radius: 12px; font-size: 14px; z-index: 99999;
      backdrop-filter: blur(10px); border: 1px solid rgba(255,255,255,0.1);
    `
    document.body.appendChild(msg)
  }

  setTimeout(() => {
    sessionExpiring = false
    window.location.href = '/login'
  }, 1500)
}

/** Update the module-level token expiry from a login/refresh response. */
export function setTokenExpiry(expiresInSeconds: number) {
  tokenExpiryMs = Date.now() + expiresInSeconds * 1000
  persistTokenExpiry(tokenExpiryMs)
  scheduleProactiveRefresh()
}

/** Clear stored token expiry (used on logout). */
export function clearTokenExpiry() {
  tokenExpiryMs = null
  persistTokenExpiry(null)
  clearProactiveRefresh()
}

/** Schedule a proactive token refresh 5 minutes before expiry. */
function scheduleProactiveRefresh() {
  clearProactiveRefresh()
  if (!tokenExpiryMs) return

  const refreshAt = tokenExpiryMs - 5 * 60 * 1000 // 5 min before expiry
  const delay = refreshAt - Date.now()

  if (delay > 0) {
    proactiveRefreshTimer = setTimeout(() => doRefresh(), delay)
  }
}

function clearProactiveRefresh() {
  if (proactiveRefreshTimer) {
    clearTimeout(proactiveRefreshTimer)
    proactiveRefreshTimer = null
  }
}

// Shared promise so concurrent callers wait for the same in-flight refresh
let refreshPromise: Promise<boolean> | null = null

/** Perform a token refresh (used by both proactive and reactive paths). */
async function doRefresh(): Promise<boolean> {
  // If a refresh is already in flight, piggyback on it instead of returning false
  if (isRefreshing && refreshPromise) return refreshPromise

  isRefreshing = true

  refreshPromise = (async () => {
    try {
      const res = await axios.post('/api/auth/refresh', undefined, {
        withCredentials: true,
      })
      const { access_token } = res.data

      // Extract expiry from the response token for proactive refresh scheduling
      try {
        const payload = JSON.parse(atob(access_token.split('.')[1]))
        if (payload.exp) {
          tokenExpiryMs = payload.exp * 1000
        }
      } catch {
        // If token parsing fails, fall back to 4 hours (matches backend default)
        tokenExpiryMs = Date.now() + 240 * 60 * 1000
      }
      persistTokenExpiry(tokenExpiryMs)

      refreshRetryCount = 0
      isRefreshing = false
      refreshPromise = null

      onTokenRefreshed()
      scheduleProactiveRefresh()

      return true
    } catch {
      isRefreshing = false
      refreshPromise = null
      onRefreshFailed()
      return false
    }
  })()

  return refreshPromise
}

// No request interceptor needed — httpOnly cookies are sent automatically
// via withCredentials: true

// Response interceptor: handle 401 with token refresh
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config

    // Skip refresh logic for login/register — they return 401 for invalid
    // credentials, not for expired tokens. /auth/me MUST attempt refresh
    // so the app can recover after token expiry (especially on PWA resume).
    const isAuthEndpoint = originalRequest.url?.includes('/auth/login')
      || originalRequest.url?.includes('/auth/register')
    if (error.response?.status === 401 && !originalRequest._retry && !isAuthEndpoint) {
      originalRequest._retry = true

      // If already refreshing, queue this request
      if (isRefreshing) {
        return new Promise((resolve) => {
          subscribeTokenRefresh(() => {
            resolve(api(originalRequest))
          })
        })
      }

      // Check max retries
      if (refreshRetryCount >= MAX_REFRESH_RETRIES) {
        refreshRetryCount = 0
        handleSessionExpiry()
        return Promise.reject(error)
      }

      refreshRetryCount++

      const refreshed = await doRefresh()
      if (refreshed) {
        return api(originalRequest)
      }

      handleSessionExpiry()
      return Promise.reject(error)
    }

    return Promise.reject(error)
  }
)

// Re-schedule proactive refresh when tab becomes visible (user returns after sleep/idle).
// On PWA resume the JS context may have been killed, so tokenExpiryMs could be null
// even though the refresh-token cookie is still valid — always attempt recovery.
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState !== 'visible') return

  // Re-hydrate from localStorage in case the module was re-initialized (PWA kill)
  if (!tokenExpiryMs) {
    tokenExpiryMs = loadTokenExpiry()
  }

  if (!tokenExpiryMs) {
    // No expiry in memory or localStorage — user was never logged in or explicitly
    // logged out. Don't spam the server with refresh attempts on every tab focus.
    return
  }

  const timeLeft = tokenExpiryMs - Date.now()
  if (timeLeft <= 5 * 60 * 1000) {
    // Token expired or about to expire — refresh immediately
    doRefresh()
  } else {
    scheduleProactiveRefresh()
  }
})

// Sync token expiry across tabs (logout in one tab clears all)
window.addEventListener('storage', (e) => {
  if (e.key === TOKEN_EXPIRY_KEY) {
    tokenExpiryMs = e.newValue ? Number(e.newValue) : null
    if (!tokenExpiryMs) {
      clearProactiveRefresh()
    } else {
      scheduleProactiveRefresh()
    }
  }
})

export default api
