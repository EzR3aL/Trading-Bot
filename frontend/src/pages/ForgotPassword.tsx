import { useState, FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { TrendingUp, Loader2, Eye, EyeOff, ArrowLeft, CheckCircle } from 'lucide-react'
import api from '../api/client'
import axios from 'axios'

export default function ForgotPassword() {
  const { t } = useTranslation()
  const navigate = useNavigate()

  // Step 1: Request reset token
  const [username, setUsername] = useState('')
  const [isRequestingToken, setIsRequestingToken] = useState(false)
  const [isTokenRequested, setIsTokenRequested] = useState(false)

  // Step 2: Reset password with token
  const [token, setToken] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [isResetting, setIsResetting] = useState(false)
  const [error, setError] = useState('')
  const [successMessage, setSuccessMessage] = useState('')

  const handleRequestToken = async (e: FormEvent) => {
    e.preventDefault()
    setError('')
    setIsRequestingToken(true)
    try {
      await api.post('/auth/forgot-password', { username })
      setIsTokenRequested(true)
    } catch {
      // Always show success to avoid revealing if user exists
      setIsTokenRequested(true)
    } finally {
      setIsRequestingToken(false)
    }
  }

  const handleResetPassword = async (e: FormEvent) => {
    e.preventDefault()
    setError('')

    if (newPassword !== confirmPassword) {
      setError(t('forgotPassword.passwordMismatch'))
      return
    }

    setIsResetting(true)
    try {
      await api.post('/auth/reset-password', {
        token,
        new_password: newPassword,
      })
      setSuccessMessage(t('forgotPassword.resetSuccess'))
      setTimeout(() => navigate('/login'), 3000)
    } catch (err) {
      if (axios.isAxiosError(err) && err.response?.data?.detail) {
        setError(err.response.data.detail)
      } else {
        setError(t('forgotPassword.resetError'))
      }
    } finally {
      setIsResetting(false)
    }
  }

  return (
    <div className="min-h-screen login-bg flex items-center justify-center px-4">
      <div className="w-full max-w-sm animate-in">
        <div className="glass-card rounded-2xl p-8 shadow-2xl">
          {/* Logo */}
          <div className="flex justify-center mb-6">
            <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-primary-500 to-primary-700 flex items-center justify-center shadow-glow">
              <TrendingUp size={28} className="text-white" />
            </div>
          </div>

          <h1 className="text-2xl font-bold text-white mb-1 text-center tracking-tight">
            Trading Bot
          </h1>
          <h2 className="text-sm text-gray-400 mb-8 text-center">
            {t('forgotPassword.title')}
          </h2>

          {/* Success message after password reset */}
          {successMessage && (
            <div className="mb-6 p-3 bg-emerald-500/10 border border-emerald-500/20 rounded-xl text-emerald-400 text-sm text-center flex items-center justify-center gap-2">
              <CheckCircle size={16} />
              {successMessage}
            </div>
          )}

          {/* Error message */}
          {error && (
            <div role="alert" className="mb-6 p-3 bg-red-500/10 border border-red-500/20 rounded-xl text-red-400 text-sm text-center">
              {error}
            </div>
          )}

          {/* Step 1: Request token */}
          {!isTokenRequested && !successMessage && (
            <form onSubmit={handleRequestToken} className="space-y-5">
              <div>
                <label htmlFor="forgot-username" className="block text-xs text-gray-400 mb-1.5 font-medium uppercase tracking-wider">
                  {t('forgotPassword.usernameLabel')}
                </label>
                <input
                  id="forgot-username"
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  className="input-dark"
                  required
                  autoFocus
                  autoComplete="username"
                />
              </div>
              <button
                type="submit"
                disabled={isRequestingToken}
                className="btn-gradient w-full py-3 flex items-center justify-center gap-2"
              >
                {isRequestingToken ? (
                  <>
                    <Loader2 size={16} className="animate-spin" />
                    {t('common.loading')}
                  </>
                ) : (
                  t('forgotPassword.requestButton')
                )}
              </button>
            </form>
          )}

          {/* Token requested confirmation + Step 2 */}
          {isTokenRequested && !successMessage && (
            <>
              <div className="mb-6 p-3 bg-emerald-500/10 border border-emerald-500/20 rounded-xl text-emerald-400 text-sm text-center">
                {t('forgotPassword.successMessage')}
              </div>

              <h3 className="text-sm font-medium text-gray-300 mb-4 text-center">
                {t('forgotPassword.step2Title')}
              </h3>

              <form onSubmit={handleResetPassword} className="space-y-5">
                <div>
                  <label htmlFor="reset-token" className="block text-xs text-gray-400 mb-1.5 font-medium uppercase tracking-wider">
                    {t('forgotPassword.tokenLabel')}
                  </label>
                  <input
                    id="reset-token"
                    type="text"
                    value={token}
                    onChange={(e) => setToken(e.target.value)}
                    className="input-dark"
                    required
                    autoFocus
                    placeholder={t('forgotPassword.tokenPlaceholder')}
                    autoComplete="off"
                  />
                </div>
                <div>
                  <label htmlFor="new-password" className="block text-xs text-gray-400 mb-1.5 font-medium uppercase tracking-wider">
                    {t('forgotPassword.newPasswordLabel')}
                  </label>
                  <div className="relative">
                    <input
                      id="new-password"
                      type={showPassword ? 'text' : 'password'}
                      value={newPassword}
                      onChange={(e) => setNewPassword(e.target.value)}
                      className="input-dark pr-10"
                      required
                      autoComplete="new-password"
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword(!showPassword)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-300 transition-colors"
                      aria-label={showPassword ? t('forgotPassword.hidePassword') : t('forgotPassword.showPassword')}
                    >
                      {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                    </button>
                  </div>
                </div>
                <div>
                  <label htmlFor="confirm-password" className="block text-xs text-gray-400 mb-1.5 font-medium uppercase tracking-wider">
                    {t('forgotPassword.confirmPasswordLabel')}
                  </label>
                  <input
                    id="confirm-password"
                    type={showPassword ? 'text' : 'password'}
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    className="input-dark"
                    required
                    autoComplete="new-password"
                  />
                </div>
                <button
                  type="submit"
                  disabled={isResetting}
                  className="btn-gradient w-full py-3 flex items-center justify-center gap-2"
                >
                  {isResetting ? (
                    <>
                      <Loader2 size={16} className="animate-spin" />
                      {t('common.loading')}
                    </>
                  ) : (
                    t('forgotPassword.resetButton')
                  )}
                </button>
              </form>
            </>
          )}

          {/* Back to login link */}
          <div className="mt-6 text-center">
            <Link
              to="/login"
              className="text-sm text-gray-400 hover:text-primary-400 transition-colors inline-flex items-center gap-1.5"
            >
              <ArrowLeft size={14} />
              {t('forgotPassword.backToLogin')}
            </Link>
          </div>
        </div>
      </div>
    </div>
  )
}
