import { useState, FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuthStore } from '../stores/authStore'
import { Loader2 } from 'lucide-react'
import EdgeBotsLogo from '../components/ui/EdgeBotsLogo'
import FormField from '../components/ui/FormField'
import { loginSchema, validateField } from '../utils/validation'
import { showError } from '../utils/toast'
import { useDocumentTitle } from '../hooks/useDocumentTitle'

export default function Login() {
  const { t } = useTranslation()
  useDocumentTitle(t('login.title'))
  const navigate = useNavigate()
  const { login, isLoading } = useAuthStore()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [fieldErrors, setFieldErrors] = useState<Record<string, string | null>>({})

  const validateSingleField = (field: 'username' | 'password', value: string) => {
    const schema = loginSchema.shape[field]
    const msg = validateField(schema, value)
    setFieldErrors((prev) => ({ ...prev, [field]: msg }))
  }

  const handleLoginSubmit = async (e: FormEvent) => {
    e.preventDefault()

    // Validate the full form before submission
    const result = loginSchema.safeParse({ username, password })
    if (!result.success) {
      const errs: Record<string, string | null> = {}
      for (const issue of result.error.issues) {
        const key = String(issue.path[0])
        if (!errs[key]) errs[key] = issue.message
      }
      setFieldErrors(errs)
      return
    }

    try {
      await login(username, password)
      navigate('/')
    } catch {
      showError(t('login.error'))
    }
  }

  return (
    <div className="min-h-screen login-bg flex items-center justify-center px-4">
      <div className="w-full max-w-sm animate-in">
        <div className="glass-card rounded-2xl p-8 shadow-2xl">
          {/* Logo */}
          <div className="flex justify-center mb-6">
            <EdgeBotsLogo size={56} />
          </div>

          <h1 className="text-2xl font-bold text-white mb-1 text-center tracking-tight">
            Edge Bots
          </h1>
          <h2 className="text-sm text-gray-400 mb-8 text-center">
            {t('login.title')}
          </h2>

          <form onSubmit={handleLoginSubmit} className="space-y-5">
            <FormField
              label={t('login.username')}
              htmlFor="login-username"
              error={fieldErrors.username}
              required
            >
              <input
                id="login-username"
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                onBlur={() => validateSingleField('username', username)}
                className={`input-dark ${fieldErrors.username ? 'border-red-500/50' : ''}`}
                autoFocus
                autoComplete="username"
                aria-invalid={!!fieldErrors.username}
                aria-describedby={fieldErrors.username ? 'login-username-error' : undefined}
              />
            </FormField>

            <FormField
              label={t('login.password')}
              htmlFor="login-password"
              error={fieldErrors.password}
              required
            >
              <input
                id="login-password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                onBlur={() => validateSingleField('password', password)}
                className={`input-dark ${fieldErrors.password ? 'border-red-500/50' : ''}`}
                autoComplete="current-password"
                aria-invalid={!!fieldErrors.password}
                aria-describedby={fieldErrors.password ? 'login-password-error' : undefined}
              />
            </FormField>

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
        </div>
      </div>
    </div>
  )
}
