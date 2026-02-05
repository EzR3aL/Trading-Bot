import { Link, useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuthStore } from '../../stores/authStore'
import ChatButton from '../assistant/ChatButton'
import ChatPanel from '../assistant/ChatPanel'
import {
  LayoutDashboard,
  ArrowLeftRight,
  Layers,
  Settings,
  Bot,
  Cpu,
  FileText,
  Users,
  BookOpen,
  type LucideIcon,
} from 'lucide-react'

const navItems: { path: string; key: string; icon: LucideIcon }[] = [
  { path: '/', key: 'dashboard', icon: LayoutDashboard },
  { path: '/bots', key: 'myBots', icon: Cpu },
  { path: '/trades', key: 'trades', icon: ArrowLeftRight },
  { path: '/presets', key: 'presets', icon: Layers },
  { path: '/settings', key: 'settings', icon: Settings },
  { path: '/bot', key: 'botControl', icon: Bot },
  { path: '/tax-report', key: 'taxReport', icon: FileText },
  { path: '/guide', key: 'guide', icon: BookOpen },
]

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { t, i18n } = useTranslation()
  const location = useLocation()
  const { user, logout } = useAuthStore()

  const toggleLang = () => {
    const next = i18n.language === 'de' ? 'en' : 'de'
    i18n.changeLanguage(next)
    localStorage.setItem('language', next)
  }

  return (
    <div className="min-h-screen bg-gray-950">
      {/* Sidebar */}
      <aside className="fixed top-0 left-0 h-full w-56 bg-gray-900 border-r border-gray-800 flex flex-col">
        <div className="p-4 border-b border-gray-800">
          <h1 className="text-lg font-bold text-white">Trading Bot</h1>
          <p className="text-xs text-gray-400">v2.0</p>
        </div>

        <nav className="flex-1 py-4">
          {navItems.map((item) => {
            const Icon = item.icon
            return (
              <Link
                key={item.path}
                to={item.path}
                className={`flex items-center gap-3 px-4 py-2.5 text-sm transition-colors ${
                  location.pathname === item.path
                    ? 'bg-primary-600/20 text-primary-400 border-r-2 border-primary-400'
                    : 'text-gray-400 hover:text-white hover:bg-gray-800'
                }`}
              >
                <Icon size={18} />
                {t(`nav.${item.key}`)}
              </Link>
            )
          })}
          {user?.role === 'admin' && (
            <Link
              to="/admin/users"
              className={`flex items-center gap-3 px-4 py-2.5 text-sm transition-colors ${
                location.pathname === '/admin/users'
                  ? 'bg-primary-600/20 text-primary-400 border-r-2 border-primary-400'
                  : 'text-gray-400 hover:text-white hover:bg-gray-800'
              }`}
            >
              <Users size={18} />
              {t('nav.admin')}
            </Link>
          )}
        </nav>

        <div className="p-4 border-t border-gray-800 space-y-2">
          <div className="text-sm text-gray-400">
            {user?.username} ({user?.role})
          </div>
          <div className="flex gap-2">
            <button
              onClick={toggleLang}
              className="px-2 py-1 text-xs bg-gray-800 text-gray-300 rounded hover:bg-gray-700"
            >
              {i18n.language === 'de' ? 'EN' : 'DE'}
            </button>
            <button
              onClick={logout}
              className="px-2 py-1 text-xs bg-red-900/50 text-red-400 rounded hover:bg-red-900"
            >
              {t('nav.logout')}
            </button>
          </div>
        </div>
      </aside>

      {/* Main content */}
      <main className="ml-56 p-6">{children}</main>

      {/* AI Assistant */}
      <ChatButton />
      <ChatPanel />
    </div>
  )
}
