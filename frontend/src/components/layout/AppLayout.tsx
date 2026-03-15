import { useState, useMemo } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuthStore } from '../../stores/authStore'
import { useFilterStore, type DemoFilter } from '../../stores/filterStore'
import { useRealtimeStore } from '../../stores/realtimeStore'
import { useToastStore } from '../../stores/toastStore'
import { useWebSocket } from '../../hooks/useWebSocket'
import {
  LayoutDashboard,
  ArrowLeftRight,
  Layers,
  Settings,
  Bot,
  FileText,
  Users,
  BookOpen,
  TrendingUp,
  FlaskConical,
  Briefcase,
  Menu,
  X,
  Sun,
  Moon,
  WifiOff,
  type LucideIcon,
} from 'lucide-react'
import { useThemeStore } from '../../stores/themeStore'
import OfflineIndicator from '../ui/OfflineIndicator'

const navItems: { path: string; key: string; icon: LucideIcon }[] = [
  { path: '/', key: 'dashboard', icon: LayoutDashboard },
  { path: '/portfolio', key: 'portfolio', icon: Briefcase },
  { path: '/bots', key: 'myBots', icon: Bot },
  { path: '/performance', key: 'performance', icon: TrendingUp },
  { path: '/backtest', key: 'backtest', icon: FlaskConical },
  { path: '/trades', key: 'trades', icon: ArrowLeftRight },
  { path: '/presets', key: 'presets', icon: Layers },
  { path: '/settings', key: 'settings', icon: Settings },
  { path: '/tax-report', key: 'taxReport', icon: FileText },
  { path: '/guide', key: 'guide', icon: BookOpen },
]

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { t, i18n } = useTranslation()
  const location = useLocation()
  const { user, logout } = useAuthStore()
  const { demoFilter, setDemoFilter } = useFilterStore()
  const { theme, toggleTheme } = useThemeStore()
  const [mobileOpen, setMobileOpen] = useState(false)
  const { pushEvent, updateBotStatus } = useRealtimeStore()
  const { addToast } = useToastStore()

  // WebSocket handlers — memoised so the hook doesn't reconnect on every render
  const wsHandlers = useMemo(() => ({
    bot_started: (data: unknown) => {
      const d = data as { bot_id: number; status?: unknown }
      pushEvent('bot_started', d)
      if (d.status) updateBotStatus(d.bot_id, d.status)
      addToast('info', t('ws.botStarted', { defaultValue: 'Bot started' }))
    },
    bot_stopped: (data: unknown) => {
      const d = data as { bot_id: number }
      pushEvent('bot_stopped', d)
      updateBotStatus(d.bot_id, null)
      addToast('info', t('ws.botStopped', { defaultValue: 'Bot stopped' }))
    },
    trade_opened: (data: unknown) => {
      const d = data as { symbol?: string }
      pushEvent('trade_opened', d)
      addToast('success', t('ws.tradeOpened', { symbol: d.symbol ?? '', defaultValue: `Trade opened: ${d.symbol ?? ''}` }))
    },
    trade_closed: (data: unknown) => {
      const d = data as { symbol?: string; pnl?: number }
      pushEvent('trade_closed', d)
      const pnl = typeof d.pnl === 'number' ? ` ($${d.pnl.toFixed(2)})` : ''
      addToast('info', t('ws.tradeClosed', { symbol: d.symbol ?? '', pnl, defaultValue: `Trade closed: ${d.symbol ?? ''}${pnl}` }))
    },
  }), [pushEvent, updateBotStatus, addToast, t])

  const { status: wsStatus } = useWebSocket(wsHandlers)

  const filterOptions: { value: DemoFilter; labelKey: string }[] = [
    { value: 'all', labelKey: 'common.all' },
    { value: 'demo', labelKey: 'common.demo' },
    { value: 'live', labelKey: 'common.live' },
  ]

  const toggleLang = () => {
    const next = i18n.language === 'de' ? 'en' : 'de'
    i18n.changeLanguage(next)
    localStorage.setItem('language', next)
  }

  const closeMobile = () => setMobileOpen(false)

  const sidebarContent = (
    <>
      {/* Logo */}
      <div className="px-5 py-5 border-b border-white/5">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-primary-500 to-primary-700 flex items-center justify-center shadow-glow-sm">
            <TrendingUp size={16} className="text-white" />
          </div>
          <div>
            <h1 className="text-base font-bold text-white tracking-tight">Trading Bot</h1>
            <p className="text-[10px] text-gray-500 font-medium">v2.0</p>
          </div>
        </div>
      </div>

      {/* Navigation */}
      <nav role="navigation" className="flex-1 py-3 px-2 space-y-0.5 overflow-y-auto">
        {navItems.map((item) => {
          const Icon = item.icon
          const isActive = location.pathname === item.path
          return (
            <Link
              key={item.path}
              to={item.path}
              onClick={closeMobile}
              aria-label={t(`nav.${item.key}`)}
              className={`flex items-center gap-3 px-3 py-2.5 text-sm rounded-xl transition-all duration-200 ${
                isActive
                  ? 'nav-item-active text-white font-medium'
                  : 'text-gray-400 hover:text-white hover:bg-white/5'
              }`}
            >
              <Icon size={18} className={isActive ? 'text-primary-400' : ''} />
              <span>{t(`nav.${item.key}`)}</span>
            </Link>
          )
        })}
        {user?.role === 'admin' && (
          <Link
            to="/admin/users"
            onClick={closeMobile}
            aria-label={t('nav.admin')}
            className={`flex items-center gap-3 px-3 py-2.5 text-sm rounded-xl transition-all duration-200 ${
              location.pathname === '/admin/users'
                ? 'nav-item-active text-white font-medium'
                : 'text-gray-400 hover:text-white hover:bg-white/5'
            }`}
          >
            <Users size={18} className={location.pathname === '/admin/users' ? 'text-primary-400' : ''} />
            <span>{t('nav.admin')}</span>
          </Link>
        )}
      </nav>

      {/* Bottom controls */}
      <div className="p-4 border-t border-white/5 space-y-3">
        {/* User info */}
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-full bg-gradient-to-br from-primary-600 to-primary-800 flex items-center justify-center text-xs font-bold text-white">
            {user?.username?.charAt(0).toUpperCase() || '?'}
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-sm text-white font-medium truncate">{user?.username}</div>
            <div className="text-[10px] text-gray-400 uppercase tracking-wider">{user?.role}</div>
          </div>
        </div>

        {/* Demo/Live toggle - pill switch */}
        <div>
          <div className="text-[10px] text-gray-400 uppercase tracking-wider mb-1.5 font-medium">{t('common.demoLiveFilter')}</div>
          <div className="flex bg-white/5 rounded-xl p-0.5 border border-white/5">
            {filterOptions.map((opt) => (
              <button
                key={opt.value}
                onClick={() => setDemoFilter(opt.value)}
                aria-label={`${t('common.demoLiveFilter')}: ${t(opt.labelKey)}`}
                className={`flex-1 px-2 py-1.5 text-xs font-medium rounded-lg transition-all duration-200 ${
                  demoFilter === opt.value
                    ? 'bg-gradient-to-r from-primary-600 to-primary-500 text-white shadow-glow-sm'
                    : 'text-gray-400 hover:text-gray-200'
                }`}
              >
                {t(opt.labelKey)}
              </button>
            ))}
          </div>
        </div>

        {/* Theme, Language & Logout */}
        <div className="flex gap-2">
          <button
            onClick={toggleTheme}
            aria-label={theme === 'dark' ? t('common.lightMode') : t('common.darkMode')}
            className="px-2.5 py-1.5 text-xs bg-white/5 text-gray-300 rounded-lg hover:bg-white/10 border border-white/5 transition-all duration-200"
          >
            {theme === 'dark' ? <Sun size={14} /> : <Moon size={14} />}
          </button>
          <button
            onClick={toggleLang}
            aria-label={`Switch language to ${i18n.language === 'de' ? 'English' : 'German'}`}
            className="px-3 py-1.5 text-xs bg-white/5 text-gray-300 rounded-lg hover:bg-white/10 border border-white/5 transition-all duration-200 font-medium"
          >
            {i18n.language === 'de' ? 'EN' : 'DE'}
          </button>
          <button
            onClick={logout}
            aria-label={t('nav.logout')}
            className="flex-1 px-3 py-1.5 text-xs bg-red-500/10 text-red-400 rounded-lg hover:bg-red-500/20 border border-red-500/10 transition-all duration-200 font-medium"
          >
            {t('nav.logout')}
          </button>
        </div>
      </div>
    </>
  )

  return (
    <div className="min-h-screen bg-gradient-dark">
      <a href="#main-content" className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:bg-blue-600 focus:text-white focus:px-4 focus:py-2 focus:rounded">
        Skip to content
      </a>
      <OfflineIndicator />
      {wsStatus === 'failed' && (
        <div className="fixed top-0 left-0 right-0 z-[49] bg-red-600 text-white text-center py-2 text-sm font-medium flex items-center justify-center gap-2">
          <WifiOff className="h-4 w-4" />
          {t('ws.connectionLost', { defaultValue: 'Live connection lost. Reload the page to retry.' })}
        </div>
      )}
      {wsStatus === 'disconnected' && (
        <div className="fixed bottom-4 right-4 z-[49] bg-yellow-600/90 text-white text-xs font-medium px-3 py-1.5 rounded-lg flex items-center gap-1.5 shadow-lg backdrop-blur-sm">
          <WifiOff className="h-3.5 w-3.5" />
          {t('ws.reconnecting', { defaultValue: 'Reconnecting...' })}
        </div>
      )}
      {/* Mobile hamburger */}
      <div className="lg:hidden fixed top-0 left-0 right-0 z-40 bg-[#0a0e17]/90 backdrop-blur-xl border-b border-white/5 px-4 py-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-primary-500 to-primary-700 flex items-center justify-center">
            <TrendingUp size={14} className="text-white" />
          </div>
          <span className="text-white font-bold text-sm">Trading Bot</span>
        </div>
        <button
          onClick={() => setMobileOpen(!mobileOpen)}
          aria-label={mobileOpen ? 'Close menu' : 'Open menu'}
          className="p-2 text-gray-400 hover:text-white transition-colors"
        >
          {mobileOpen ? <X size={20} /> : <Menu size={20} />}
        </button>
      </div>

      {/* Mobile overlay */}
      {mobileOpen && (
        <div
          className="lg:hidden fixed inset-0 z-40 bg-black/60 backdrop-blur-sm overlay-fade"
          onClick={closeMobile}
        />
      )}

      {/* Mobile sidebar */}
      <aside
        className={`lg:hidden fixed top-0 left-0 h-full w-64 z-50 bg-gradient-sidebar flex flex-col border-r border-white/5 transition-transform duration-300 ${
          mobileOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        {sidebarContent}
      </aside>

      {/* Desktop sidebar */}
      <aside className="hidden lg:flex fixed top-0 left-0 h-full w-60 bg-gradient-sidebar border-r border-white/5 flex-col z-30">
        {sidebarContent}
      </aside>

      {/* Main content */}
      <main id="main-content" role="main" className="lg:ml-60 px-4 sm:px-6 py-6 pt-20 lg:pt-6 min-h-screen overflow-x-hidden">
        {children}
      </main>
    </div>
  )
}
