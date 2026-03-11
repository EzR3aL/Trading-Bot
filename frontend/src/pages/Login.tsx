import { useState, useRef, useEffect, FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuthStore } from '../stores/authStore'
import { TrendingUp, Loader2, ArrowLeft, ShieldCheck } from 'lucide-react'

export default function Login() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { login, verify2fa, isLoading } = useAuthStore()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')

  // 2FA state
  const [is2faStep, setIs2faStep] = useState(false)
  const [tempToken, setTempToken] = useState('')
  const [totpCode, setTotpCode] = useState('')
  const [isBackupMode, setIsBackupMode] = useState(false)
  const codeInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (is2faStep && codeInputRef.current) {
      codeInputRef.current.focus()
    }
  }, [is2faStep, isBackupMode])

  const handleLoginSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError('')
    try {
      const result = await login(username, password)
      if (result.requires2fa && result.tempToken) {
        setTempToken(result.tempToken)
        setIs2faStep(true)
      } else {
        navigate('/')
      }
    } catch {
      setError(t('login.error'))
    }
  }

  const handle2faSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError('')
    try {
      await verify2fa(tempToken, totpCode)
      navigate('/')
    } catch {
      setError(t('login.2fa.error'))
    }
  }

  const handleCodeChange = (value: string) => {
    if (isBackupMode) {
      setTotpCode(value)
      return
    }
    // Only allow digits for TOTP mode
    const digits = value.replace(/\D/g, '').slice(0, 6)
    setTotpCode(digits)

    // Auto-submit when 6 digits entered
    if (digits.length === 6) {
      setError('')
      verify2fa(tempToken, digits)
        .then(() => navigate('/'))
        .catch(() => {
          setError(t('login.2fa.error'))
          setTotpCode('')
        })
    }
  }

  const handleBack = () => {
    setIs2faStep(false)
    setTempToken('')
    setTotpCode('')
    setIsBackupMode(false)
    setError('')
  }

  return (
    <div className="min-h-screen login-bg flex items-center justify-center px-4">
      <div className="w-full max-w-sm animate-in">
        <div className="glass-card rounded-2xl p-8 shadow-2xl">
          {/* Logo */}
          <div className="flex justify-center mb-6">
            <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-primary-500 to-primary-700 flex items-center justify-center shadow-glow">
              {is2faStep ? (
                <ShieldCheck size={28} className="text-white" />
              ) : (
                <TrendingUp size={28} className="text-white" />
              )}
            </div>
          </div>

          <h1 className="text-2xl font-bold text-white mb-1 text-center tracking-tight">
            {is2faStep ? t('login.2fa.title') : 'Trading Bot'}
          </h1>
          <h2 className="text-sm text-gray-400 mb-8 text-center">
            {is2faStep ? t('login.2fa.codeLabel') : t('login.title')}
          </h2>

          {error && (
            <div role="alert" className="mb-6 p-3 bg-red-500/10 border border-red-500/20 rounded-xl text-red-400 text-sm text-center">
              {error}
            </div>
          )}

          {is2faStep ? (
            /* ── 2FA Step ── */
            <form onSubmit={handle2faSubmit} className="space-y-5">
              <div>
                <label htmlFor="totp-code" className="block text-xs text-gray-400 mb-1.5 font-medium uppercase tracking-wider">
                  {isBackupMode ? t('login.2fa.backupLabel') : t('login.2fa.codeLabel')}
                </label>
                {isBackupMode ? (
                  <input
                    ref={codeInputRef}
                    id="totp-code"
                    type="text"
                    value={totpCode}
                    onChange={(e) => handleCodeChange(e.target.value)}
                    className="input-dark"
                    placeholder={t('login.2fa.backupPlaceholder')}
                    required
                    autoComplete="one-time-code"
                  />
                ) : (
                  <input
                    ref={codeInputRef}
                    id="totp-code"
                    type="text"
                    inputMode="numeric"
                    value={totpCode}
                    onChange={(e) => handleCodeChange(e.target.value)}
                    className="input-dark text-center text-2xl font-mono tracking-[0.5em]"
                    placeholder={t('login.2fa.codePlaceholder')}
                    maxLength={6}
                    required
                    autoComplete="one-time-code"
                  />
                )}
              </div>

              <button
                type="button"
                onClick={() => {
                  setIsBackupMode(!isBackupMode)
                  setTotpCode('')
                  setError('')
                }}
                className="text-xs text-primary-400 hover:text-primary-300 transition-colors w-full text-center"
              >
                {isBackupMode ? t('login.2fa.codeToggle') : t('login.2fa.backupToggle')}
              </button>

              <button
                type="submit"
                disabled={isLoading || (!isBackupMode && totpCode.length < 6)}
                className="btn-gradient w-full py-3 flex items-center justify-center gap-2"
              >
                {isLoading ? (
                  <>
                    <Loader2 size={16} className="animate-spin" />
                    {t('common.loading')}
                  </>
                ) : (
                  t('login.2fa.submit')
                )}
              </button>

              <button
                type="button"
                onClick={handleBack}
                className="w-full py-2 flex items-center justify-center gap-1.5 text-sm text-gray-400 hover:text-white transition-colors"
              >
                <ArrowLeft size={14} />
                {t('login.2fa.back')}
              </button>
            </form>
          ) : (
            /* ── Credentials Step ── */
            <form onSubmit={handleLoginSubmit} className="space-y-5">
              <div>
                <label htmlFor="login-username" className="block text-xs text-gray-400 mb-1.5 font-medium uppercase tracking-wider">
                  {t('login.username')}
                </label>
                <input
                  id="login-username"
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  className="input-dark"
                  required
                  autoFocus
                  autoComplete="username"
                />
              </div>
              <div>
                <label htmlFor="login-password" className="block text-xs text-gray-400 mb-1.5 font-medium uppercase tracking-wider">
                  {t('login.password')}
                </label>
                <input
                  id="login-password"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="input-dark"
                  required
                  autoComplete="current-password"
                />
              </div>
              <button
                type="submit"
                disabled={isLoading}
                className="btn-gradient w-full py-3 flex items-center justify-center gap-2"
              >
                {isLoading ? (
                  <>
                    <Loader2 size={16} className="animate-spin" />
                    {t('common.loading')}
                  </>
                ) : (
                  t('login.submit')
                )}
              </button>
            </form>
          )}
        </div>
      </div>
    </div>
  )
}
