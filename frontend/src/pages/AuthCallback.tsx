import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuthStore } from '../stores/authStore'
import { Loader2, AlertCircle } from 'lucide-react'
import EdgeBotsLogo from '../components/ui/EdgeBotsLogo'

export default function AuthCallback() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const { exchangeAuthCode } = useAuthStore()
  const [error, setError] = useState('')

  useEffect(() => {
    const code = searchParams.get('code')
    if (!code) {
      setError(t('authCallback.noCode', 'No authorization code provided.'))
      return
    }

    let cancelled = false

    const exchange = async () => {
      try {
        await exchangeAuthCode(code)
        if (!cancelled) {
          // Remove code from URL for security, then navigate
          window.history.replaceState({}, '', '/auth/callback')
          navigate('/', { replace: true })
        }
      } catch {
        if (!cancelled) {
          setError(t('authCallback.failed', 'Authentication failed. The code may have expired.'))
        }
      }
    }

    exchange()
    return () => { cancelled = true }
  }, [searchParams, exchangeAuthCode, navigate, t])

  return (
    <div className="min-h-screen bg-[#0a0e17] flex items-center justify-center p-4">
      <div className="text-center max-w-sm">
        <div className="flex justify-center mb-6">
          <EdgeBotsLogo />
        </div>

        {error ? (
          <div className="space-y-4">
            <div className="flex items-center justify-center gap-2 text-red-400">
              <AlertCircle size={20} />
              <span className="text-sm">{error}</span>
            </div>
            <a
              href="https://www.trading-department.com"
              className="inline-block px-4 py-2 text-sm text-white bg-primary-600 hover:bg-primary-500 rounded-lg transition-colors"
            >
              {t('authCallback.backToMain', 'Back to Trading Department')}
            </a>
          </div>
        ) : (
          <div className="space-y-3">
            <Loader2 size={32} className="animate-spin text-primary-400 mx-auto" />
            <p className="text-gray-400 text-sm">
              {t('authCallback.loading', 'Signing you in...')}
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
