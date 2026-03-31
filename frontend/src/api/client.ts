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

// Module-level token expiry timestamp (ms) — set by login/refresh responses
let tokenExpiryMs: number | null = null

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
  sessionExpiring = true

  tokenExpiryMs = null
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
  scheduleProactiveRefresh()
}

/** Clear stored token expiry (used on logout). */
export function clearTokenExpiry() {
  tokenExpiryMs = null
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

/** Perform a token refresh (used by both proactive and reactive paths). */
async function doRefresh(): Promise<boolean> {
  if (isRefreshing) return false
  isRefreshing = true

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
      // If token parsing fails, fall back to 4h default
      tokenExpiryMs = Date.now() + 240 * 60 * 1000
    }

    refreshRetryCount = 0
    isRefreshing = false

    onTokenRefreshed()
    scheduleProactiveRefresh()

    return true
  } catch {
    isRefreshing = false
    onRefreshFailed()
    return false
  }
}

// No request interceptor needed — httpOnly cookies are sent automatically
// via withCredentials: true

// Response interceptor: handle 401 with token refresh
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config

    if (error.response?.status === 401 && !originalRequest._retry) {
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

// Re-schedule proactive refresh when tab becomes visible (user returns after sleep/idle)
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible' && tokenExpiryMs) {
    scheduleProactiveRefresh()
  }
})

export default api
