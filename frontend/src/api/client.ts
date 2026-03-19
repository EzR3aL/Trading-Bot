import axios from 'axios'
import i18n from '../i18n/config'

const api = axios.create({
  baseURL: '/api',
  headers: { 'Content-Type': 'application/json' },
  timeout: 15_000,
  withCredentials: true,
})

// Refresh lock to prevent multiple simultaneous refresh attempts
let isRefreshing = false
let refreshSubscribers: ((token: string) => void)[] = []
let refreshRetryCount = 0
const MAX_REFRESH_RETRIES = 3

// Proactive refresh: refresh token 5 minutes before expiry
let proactiveRefreshTimer: ReturnType<typeof setTimeout> | null = null

function subscribeTokenRefresh(cb: (token: string) => void) {
  refreshSubscribers.push(cb)
}

function onTokenRefreshed(token: string) {
  refreshSubscribers.forEach((cb) => cb(token))
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

  localStorage.removeItem('access_token')
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

/** Schedule a proactive token refresh 5 minutes before expiry. */
function scheduleProactiveRefresh() {
  clearProactiveRefresh()
  const token = localStorage.getItem('access_token')
  if (!token) return

  try {
    const payload = JSON.parse(atob(token.split('.')[1]))
    const expiresAt = payload.exp * 1000 // ms
    const refreshAt = expiresAt - 5 * 60 * 1000 // 5 min before expiry
    const delay = refreshAt - Date.now()

    if (delay > 0) {
      proactiveRefreshTimer = setTimeout(() => doRefresh(), delay)
    }
  } catch {
    // Invalid token — reactive refresh will handle it
  }
}

function clearProactiveRefresh() {
  if (proactiveRefreshTimer) {
    clearTimeout(proactiveRefreshTimer)
    proactiveRefreshTimer = null
  }
}

/** Perform a token refresh (used by both proactive and reactive paths). */
async function doRefresh(): Promise<string | null> {
  if (isRefreshing) return null
  isRefreshing = true

  try {
    const res = await axios.post('/api/auth/refresh', undefined, {
      withCredentials: true,
    })
    const { access_token } = res.data
    localStorage.setItem('access_token', access_token)

    refreshRetryCount = 0
    isRefreshing = false

    onTokenRefreshed(access_token)
    scheduleProactiveRefresh()

    return access_token
  } catch {
    isRefreshing = false
    onRefreshFailed()
    return null
  }
}

// Request interceptor: attach JWT
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

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
          subscribeTokenRefresh((token) => {
            originalRequest.headers.Authorization = `Bearer ${token}`
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

      const newToken = await doRefresh()
      if (newToken) {
        originalRequest.headers.Authorization = `Bearer ${newToken}`
        return api(originalRequest)
      }

      handleSessionExpiry()
      return Promise.reject(error)
    }

    return Promise.reject(error)
  }
)

// Start proactive refresh on load (if token exists)
scheduleProactiveRefresh()

// Re-schedule when tab becomes visible (user returns after sleep/idle)
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible' && localStorage.getItem('access_token')) {
    scheduleProactiveRefresh()
  }
})

export default api
