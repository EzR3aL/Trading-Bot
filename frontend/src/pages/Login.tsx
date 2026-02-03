import { useState, FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuthStore } from '../stores/authStore'

export default function Login() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { login, isLoading } = useAuthStore()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError('')
    try {
      await login(username, password)
      navigate('/')
    } catch {
      setError(t('login.error'))
    }
  }

  return (
    <div className="min-h-screen bg-gray-950 flex items-center justify-center">
      <div className="w-full max-w-sm">
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-8">
          <h1 className="text-2xl font-bold text-white mb-6 text-center">
            Trading Bot
          </h1>
          <h2 className="text-lg text-gray-300 mb-6 text-center">
            {t('login.title')}
          </h2>

          {error && (
            <div className="mb-4 p-3 bg-red-900/30 border border-red-800 rounded text-red-400 text-sm">
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-sm text-gray-400 mb-1">
                {t('login.username')}
              </label>
              <input
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-white focus:border-primary-500 focus:outline-none"
                required
                autoFocus
              />
            </div>
            <div>
              <label className="block text-sm text-gray-400 mb-1">
                {t('login.password')}
              </label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded text-white focus:border-primary-500 focus:outline-none"
                required
              />
            </div>
            <button
              type="submit"
              disabled={isLoading}
              className="w-full py-2.5 bg-primary-600 text-white rounded font-medium hover:bg-primary-700 disabled:opacity-50 transition-colors"
            >
              {isLoading ? t('common.loading') : t('login.submit')}
            </button>
          </form>
        </div>
      </div>
    </div>
  )
}
