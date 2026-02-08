import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  headers: { 'Content-Type': 'application/json' },
})

// Refresh lock to prevent multiple simultaneous refresh attempts
let isRefreshing = false
let refreshSubscribers: ((token: string) => void)[] = []
let refreshRetryCount = 0
const MAX_REFRESH_RETRIES = 3

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

function handleSessionExpiry() {
  localStorage.removeItem('access_token')
  localStorage.removeItem('refresh_token')

  // Show a brief message before redirect
  const msg = document.createElement('div')
  msg.textContent = 'Session expired. Redirecting to login...'
  msg.style.cssText = `
    position: fixed; top: 20px; left: 50%; transform: translateX(-50%);
    padding: 12px 24px; background: rgba(239,68,68,0.9); color: white;
    border-radius: 12px; font-size: 14px; z-index: 99999;
    backdrop-filter: blur(10px); border: 1px solid rgba(255,255,255,0.1);
  `
  document.body.appendChild(msg)

  setTimeout(() => {
    window.location.href = '/login'
  }, 1500)
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

      const refreshToken = localStorage.getItem('refresh_token')
      if (!refreshToken) {
        handleSessionExpiry()
        return Promise.reject(error)
      }

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

      isRefreshing = true
      refreshRetryCount++

      try {
        const res = await axios.post('/api/auth/refresh', {
          refresh_token: refreshToken,
        })
        const { access_token, refresh_token: newRefresh } = res.data
        localStorage.setItem('access_token', access_token)
        localStorage.setItem('refresh_token', newRefresh)

        // Reset retry count on success
        refreshRetryCount = 0
        isRefreshing = false

        // Notify all queued requests
        onTokenRefreshed(access_token)

        originalRequest.headers.Authorization = `Bearer ${access_token}`
        return api(originalRequest)
      } catch {
        isRefreshing = false
        onRefreshFailed()
        handleSessionExpiry()
        return Promise.reject(error)
      }
    }

    return Promise.reject(error)
  }
)

export default api
