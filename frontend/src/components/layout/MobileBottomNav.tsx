import { useState } from 'react'
import useSwipeToClose from '../../hooks/useSwipeToClose'
import { Link, useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuthStore } from '../../stores/authStore'
import { useFilterStore, type DemoFilter } from '../../stores/filterStore'
import { useThemeStore } from '../../stores/themeStore'
import {
  LayoutDashboard,
  ArrowLeftRight,
  Settings,
  Bot,
  FileText,
  Users,
  BookOpen,
  TrendingUp,
  FlaskConical,
  Briefcase,
  MoreHorizontal,
  X,
  Sun,
  Moon,
  LogOut,
  type LucideIcon,
} from 'lucide-react'

const primaryItems: { path: string; key: string; icon: LucideIcon }[] = [
  { path: '/', key: 'dashboard', icon: LayoutDashboard },
  { path: '/portfolio', key: 'portfolio', icon: Briefcase },
  { path: '/bots', key: 'myBots', icon: Bot },
  { path: '/performance', key: 'performance', icon: TrendingUp },
]

const moreItems: { path: string; key: string; icon: LucideIcon }[] = [
  { path: '/trades', key: 'trades', icon: ArrowLeftRight },
  { path: '/backtest', key: 'backtest', icon: FlaskConical },
  { path: '/settings', key: 'settings', icon: Settings },
  { path: '/tax-report', key: 'taxReport', icon: FileText },
  { path: '/guide', key: 'guide', icon: BookOpen },
]

export default function MobileBottomNav() {
  const { t, i18n } = useTranslation()
  const location = useLocation()
  const { user, logout } = useAuthStore()
  const { demoFilter, setDemoFilter } = useFilterStore()
  const { theme, toggleTheme } = useThemeStore()
  const [sheetOpen, setSheetOpen] = useState(false)
  const swipeSheet = useSwipeToClose({ onClose: () => setSheetOpen(false), enabled: sheetOpen })

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

  const isMoreActive = moreItems.some((item) => location.pathname === item.path)
    || location.pathname === '/admin/users'

  return (
    <>
      {/* Bottom sheet overlay */}
      {sheetOpen && (
        <div
          className="lg:hidden fixed inset-0 z-[59] bg-black/60 backdrop-blur-sm"
          onClick={() => setSheetOpen(false)}
          aria-hidden="true"
        />
      )}

      {/* Bottom sheet */}
      <div
        ref={swipeSheet.ref}
        style={sheetOpen ? swipeSheet.style : undefined}
        role="dialog"
        aria-modal={sheetOpen}
        aria-label={t('nav.more', { defaultValue: 'More' })}
        className={`lg:hidden fixed bottom-0 left-0 right-0 z-[60] bg-[#0f1420] border-t border-white/10 rounded-t-2xl transition-transform duration-300 ease-out ${
          sheetOpen ? 'translate-y-0' : 'translate-y-full'
        }`}
      >
        {/* Sheet handle */}
        <div className="flex justify-center pt-3 pb-1">
          <div className="w-10 h-1 rounded-full bg-white/20" />
        </div>

        {/* Sheet header */}
        <div className="flex items-center justify-between px-5 pb-3">
          <span className="text-sm font-semibold text-white">{t('nav.more', { defaultValue: 'More' })}</span>
          <button
            onClick={() => setSheetOpen(false)}
            className="p-1.5 rounded-lg text-gray-400 hover:text-white hover:bg-white/10 transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* Navigation grid */}
        <nav className="px-4 pb-3">
          <div className="grid grid-cols-3 gap-2">
            {moreItems.map((item) => {
              const Icon = item.icon
              const isActive = location.pathname === item.path
              return (
                <Link
                  key={item.path}
                  to={item.path}
                  onClick={() => setSheetOpen(false)}
                  className={`flex flex-col items-center gap-1.5 py-3 px-2 rounded-xl transition-all duration-200 ${
                    isActive
                      ? 'bg-primary-500/15 text-primary-400'
                      : 'text-gray-400 hover:bg-white/5 hover:text-white active:bg-white/10'
                  }`}
                >
                  <Icon size={20} />
                  <span className="text-[11px] font-medium">{t(`nav.${item.key}`)}</span>
                </Link>
              )
            })}
            {user?.role === 'admin' && (
              <Link
                to="/admin/users"
                onClick={() => setSheetOpen(false)}
                className={`flex flex-col items-center gap-1.5 py-3 px-2 rounded-xl transition-all duration-200 ${
                  location.pathname === '/admin/users'
                    ? 'bg-primary-500/15 text-primary-400'
                    : 'text-gray-400 hover:bg-white/5 hover:text-white active:bg-white/10'
                }`}
              >
                <Users size={20} />
                <span className="text-[11px] font-medium">{t('nav.admin')}</span>
              </Link>
            )}
          </div>
        </nav>

        {/* Divider */}
        <div className="mx-4 border-t border-white/5" />

        {/* User & Controls */}
        <div className="px-4 py-3 space-y-3">
          {/* User info row */}
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-full bg-gradient-to-br from-primary-600 to-primary-800 flex items-center justify-center text-xs font-bold text-white">
              {user?.username?.charAt(0).toUpperCase() || '?'}
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-sm text-white font-medium truncate">{user?.username}</div>
              <div className="text-[10px] text-gray-500 uppercase tracking-wider">{user?.role}</div>
            </div>
          </div>

          {/* Demo/Live filter */}
          <div className="flex bg-white/5 rounded-xl p-0.5 border border-white/5">
            {filterOptions.map((opt) => (
              <button
                key={opt.value}
                onClick={() => setDemoFilter(opt.value)}
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

          {/* Theme, Language & Logout */}
          <div className="flex gap-2">
            <button
              onClick={toggleTheme}
              className="px-3 py-2 text-xs bg-white/5 text-gray-300 rounded-lg hover:bg-white/10 border border-white/5 transition-all"
            >
              {theme === 'dark' ? <Sun size={14} /> : <Moon size={14} />}
            </button>
            <button
              onClick={toggleLang}
              className="px-3 py-2 text-xs bg-white/5 text-gray-300 rounded-lg hover:bg-white/10 border border-white/5 transition-all font-medium"
            >
              {i18n.language === 'de' ? 'EN' : 'DE'}
            </button>
            <button
              onClick={() => { setSheetOpen(false); logout() }}
              className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 text-xs bg-red-500/10 text-red-400 rounded-lg hover:bg-red-500/20 border border-red-500/10 transition-all font-medium"
            >
              <LogOut size={13} />
              {t('nav.logout')}
            </button>
          </div>
        </div>

        {/* Safe area spacer for phones with home indicator */}
        <div className="h-[env(safe-area-inset-bottom,0px)]" />
      </div>

      {/* Bottom navigation bar */}
      <nav aria-label="Main navigation" className="lg:hidden fixed bottom-0 left-0 right-0 z-[58] bg-[#0a0e17]/95 backdrop-blur-xl border-t border-white/10">
        <div className="flex items-stretch">
          {primaryItems.map((item) => {
            const Icon = item.icon
            const isActive = location.pathname === item.path
            return (
              <Link
                key={item.path}
                to={item.path}
                className={`flex-1 flex flex-col items-center gap-0.5 py-2.5 min-w-0 transition-colors duration-200 ${
                  isActive ? 'text-primary-400' : 'text-gray-500 active:text-gray-300'
                }`}
              >
                <Icon size={20} strokeWidth={isActive ? 2.2 : 1.8} />
                <span className={`text-[10px] ${isActive ? 'font-semibold' : 'font-medium'}`}>
                  {t(`nav.${item.key}`)}
                </span>
              </Link>
            )
          })}
          {/* More button */}
          <button
            onClick={() => setSheetOpen(!sheetOpen)}
            className={`flex-1 flex flex-col items-center gap-0.5 py-2.5 min-w-0 transition-colors duration-200 ${
              isMoreActive || sheetOpen ? 'text-primary-400' : 'text-gray-500 active:text-gray-300'
            }`}
          >
            <MoreHorizontal size={20} strokeWidth={isMoreActive || sheetOpen ? 2.2 : 1.8} />
            <span className={`text-[10px] ${isMoreActive || sheetOpen ? 'font-semibold' : 'font-medium'}`}>
              {t('nav.more', { defaultValue: 'More' })}
            </span>
          </button>
        </div>
        {/* Safe area spacer */}
        <div className="h-[env(safe-area-inset-bottom,0px)] bg-[#0a0e17]" />
      </nav>
    </>
  )
}
