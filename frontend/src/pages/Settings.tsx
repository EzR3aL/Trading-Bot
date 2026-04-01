import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronDown, Search, CheckCircle, Clock, Users, Activity, Wifi, WifiOff, Shield, Zap, BarChart3, TrendingUp, Database, Cpu, DollarSign, ExternalLink, Settings2 } from 'lucide-react'
import Pagination from '../components/ui/Pagination'
import api from '../api/client'
import { getApiErrorMessage } from '../utils/api-error'
import { useAuthStore } from '../stores/authStore'
import { useToastStore } from '../stores/toastStore'
import type { ConnectionsStatusResponse, ExchangeConnectionStatus, ExchangeInfo, ServiceStatus, AdminUidEntry, HlRevenueInfo } from '../types'
import { ExchangeIcon } from '../components/ui/ExchangeLogo'
import FilterDropdown from '../components/ui/FilterDropdown'
import GuidedTour, { TourHelpButton, type TourStep } from '../components/ui/GuidedTour'
import HyperliquidSetup from '../components/hyperliquid/HyperliquidSetup'

const BASE_TABS = ['apiKeys'] as const
const ADMIN_TABS = [...BASE_TABS, 'connections', 'affiliateLinks', 'hyperliquid'] as const

/* ------------------------------------------------------------------ */
/*  Inline Key Form (used inside accordion)                           */
/* ------------------------------------------------------------------ */

function KeyForm({
  label, configured, keyValue, secretValue, passphraseValue,
  onKeyChange, onSecretChange, onPassphraseChange,
  onSave, onTest, saving, t, showPassphrase, authType,
}: {
  label: string
  configured: boolean
  keyValue: string
  secretValue: string
  passphraseValue: string
  onKeyChange: (v: string) => void
  onSecretChange: (v: string) => void
  onPassphraseChange: (v: string) => void
  onSave: () => void
  onTest: () => void
  saving: boolean
  t: (key: string) => string
  showPassphrase?: boolean
  authType?: string
}) {
  const isWallet = authType === 'eth_wallet'
  const keyLabel = isWallet ? t('settings.walletAddress') : t('settings.apiKey')
  const secretLabel = isWallet ? t('settings.privateKey') : t('settings.apiSecret')
  const keyPlaceholder = configured ? '****configured****' : isWallet ? '0x... (Main Wallet)' : ''
  const secretPlaceholder = isWallet ? '0x... (API Wallet Key)' : ''

  // Inline validation for wallet addresses / private keys
  const addrRegex = /^0x[0-9a-fA-F]{40}$/
  const keyRegex = /^(0x)?[0-9a-fA-F]{64}$/
  const addrError = isWallet && keyValue && !addrRegex.test(keyValue)
    ? t('settings.validationAddress') : ''
  const pkError = isWallet && secretValue && !keyRegex.test(secretValue)
    ? t('settings.validationPrivateKey') : ''

  const formId = label.toLowerCase().replace(/\s+/g, '-')

  const isLive = label.toLowerCase().includes('live') || label.toLowerCase().includes('mainnet')
  const isDemo = label.toLowerCase().includes('demo') || label.toLowerCase().includes('testnet')

  const sectionBorder = isLive
    ? 'border-l-4 border-l-red-500 bg-red-500/5 dark:bg-red-950/20'
    : isDemo
      ? 'border-l-4 border-l-amber-500 bg-amber-500/5 dark:bg-amber-950/20'
      : ''

  const badgeClass = isLive
    ? 'bg-red-500/10 text-red-600 dark:text-red-400 border border-red-500/20 dark:border-red-500/40 ring-1 ring-red-500/10 dark:ring-red-500/20'
    : isDemo
      ? 'bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-500/20 dark:border-amber-500/40 ring-1 ring-amber-500/10 dark:ring-amber-500/20'
      : 'text-gray-400'

  return (
    <div className={`space-y-3 rounded-lg p-4 ${sectionBorder}`}>
      <div className="flex items-center gap-2">
        {(isLive || isDemo) && (
          <span className={`w-2.5 h-2.5 rounded-full ${isLive ? 'bg-red-500 animate-pulse' : 'bg-amber-500'}`} />
        )}
        <span className={`inline-block text-sm font-bold uppercase tracking-wider ${badgeClass} ${(isLive || isDemo) ? 'px-3 py-1 rounded-md' : ''}`}>
          {label}
        </span>
      </div>
      {isWallet && (
        <div className="p-2.5 bg-blue-500/5 dark:bg-blue-900/20 border border-blue-500/20 dark:border-blue-800/40 rounded text-xs text-blue-600 dark:text-blue-300">
          {t('settings.hyperliquidHint')}
        </div>
      )}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div>
          <label htmlFor={`${formId}-key`} className="block text-xs text-gray-500 mb-1">{keyLabel}</label>
          <input id={`${formId}-key`} type={isWallet ? 'text' : 'password'} value={keyValue} onChange={(e) => onKeyChange(e.target.value)}
            placeholder={keyPlaceholder}
            className={`filter-select w-full text-sm font-mono ${addrError ? '!border-red-500' : ''}`} />
          {addrError && <p className="text-xs text-red-400 mt-1">{addrError}</p>}
        </div>
        <div>
          <label htmlFor={`${formId}-secret`} className="block text-xs text-gray-500 mb-1">{secretLabel}</label>
          <input id={`${formId}-secret`} type="password" value={secretValue} onChange={(e) => onSecretChange(e.target.value)}
            placeholder={secretPlaceholder}
            className={`filter-select w-full text-sm ${pkError ? '!border-red-500' : ''}`} />
          {pkError && <p className="text-xs text-red-400 mt-1">{pkError}</p>}
        </div>
        {showPassphrase !== false && (
          <div>
            <label htmlFor={`${formId}-passphrase`} className="block text-xs text-gray-500 mb-1">{t('settings.passphrase')}</label>
            <input id={`${formId}-passphrase`} type="password" value={passphraseValue} onChange={(e) => onPassphraseChange(e.target.value)}
              className="filter-select w-full text-sm" />
          </div>
        )}
      </div>
      <div className="flex gap-2">
        <button onClick={onSave} disabled={saving}
          className="px-3 py-1.5 text-sm bg-primary-600 text-white rounded hover:bg-primary-700 disabled:opacity-50">
          {t('settings.save')}
        </button>
        <button onClick={onTest} disabled={!configured}
          className="px-3 py-1.5 text-sm bg-gray-700 text-white rounded hover:bg-gray-600 disabled:opacity-50">
          {t('settings.testConnection')}
        </button>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Per-Exchange Key Form State                                       */
/* ------------------------------------------------------------------ */

interface ExchangeKeyForm {
  apiKey: string; apiSecret: string; passphrase: string
  demoApiKey: string; demoApiSecret: string; demoPassphrase: string
}

const emptyForm = (): ExchangeKeyForm => ({
  apiKey: '', apiSecret: '', passphrase: '',
  demoApiKey: '', demoApiSecret: '', demoPassphrase: '',
})

/* ------------------------------------------------------------------ */
/*  Main Settings Page                                                */
/* ------------------------------------------------------------------ */

export default function Settings() {
  const { t } = useTranslation()
  const user = useAuthStore((s) => s.user)
  const isAdmin = user?.role === 'admin'
  const TABS = useMemo(() => isAdmin ? ADMIN_TABS : BASE_TABS, [isAdmin])
  const [activeTab, setActiveTab] = useState<typeof ADMIN_TABS[number]>('apiKeys')
  const [exchanges, setExchanges] = useState<ExchangeInfo[]>([])
  const [connections, setConnections] = useState<ExchangeConnectionStatus[]>([])
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')

  // Per-exchange API key forms
  const [keyForms, setKeyForms] = useState<Record<string, ExchangeKeyForm>>({})

  // Accordion state
  const [openExchange, setOpenExchange] = useState<string | null>(null)

  // Connections status
  const [connStatus, setConnStatus] = useState<ConnectionsStatusResponse | null>(null)
  const [connLoading, setConnLoading] = useState(false)

  // Hyperliquid referral (user-facing)
  const [hlReferralInfo, setHlReferralInfo] = useState<{ referral_code?: string; referral_required?: boolean; referral_verified?: boolean; needs_referral?: boolean } | null>(null)
  // Track whether to show inline HL setup after saving credentials
  const [hlSetupVisible, setHlSetupVisible] = useState(false)

  // Hyperliquid revenue
  const [hlRevenue, setHlRevenue] = useState<HlRevenueInfo | null>(null)
  const [hlLoading, setHlLoading] = useState(false)
  // Hyperliquid admin settings
  const [hlAdminSettings, setHlAdminSettings] = useState<{
    builder_address: string; builder_fee: number; referral_code: string;
    sources: Record<string, string>;
  } | null>(null)
  const [hlAdminForm, setHlAdminForm] = useState({ builder_address: '', builder_fee: 10, referral_code: '' })
  const [hlAdminSaving, setHlAdminSaving] = useState(false)

  // Affiliate links (admin)
  const [affiliateLinks, setAffiliateLinks] = useState<Record<string, { affiliate_url: string; label: string; is_active: boolean }>>({})
  const [affiliateForms, setAffiliateForms] = useState<Record<string, { url: string; label: string; active: boolean; uidRequired: boolean }>>({})
  const [affiliateLoaded, setAffiliateLoaded] = useState(false)
  const [affiliateCardOpen, setAffiliateCardOpen] = useState<Record<string, boolean>>({})

  // Affiliate UID (user-facing)
  const [userAffiliateLinks, setUserAffiliateLinks] = useState<Record<string, { affiliate_url: string; label: string | null; uid_required: boolean }>>({})
  const [uidForms, setUidForms] = useState<Record<string, string>>({})

  // Admin UID management (paginated)
  const [adminUids, setAdminUids] = useState<AdminUidEntry[]>([])
  const [adminUidPage, setAdminUidPage] = useState(1)
  const [adminUidPages, setAdminUidPages] = useState(1)
  const [adminUidTotal, setAdminUidTotal] = useState(0)
  const [adminUidSearch, setAdminUidSearch] = useState('')
  const [adminUidFilter, setAdminUidFilter] = useState<'all' | 'pending' | 'verified'>('all')
  const [adminUidStats, setAdminUidStats] = useState({ total: 0, verified: 0, pending: 0 })

  useEffect(() => {
    const load = async () => {
      // Fetch exchanges first (no auth needed) -- always works
      try {
        const exchRes = await api.get('/exchanges')
        setExchanges(exchRes.data.exchanges)
      } catch {
        setMessage(t('common.error'))
      }

      // Fetch auth-required data independently so one failure doesn't block others
      const [configRes, connRes, affRes] = await Promise.allSettled([
        api.get('/config'),
        api.get('/config/exchange-connections'),
        api.get('/affiliate-links'),
      ])

      if (connRes.status === 'fulfilled') {
        setConnections(connRes.value.data.connections || [])
      }
      if (affRes.status === 'fulfilled') {
        const affMap: Record<string, { affiliate_url: string; label: string | null; uid_required: boolean }> = {}
        for (const link of affRes.value.data) {
          affMap[link.exchange_type] = link
        }
        setUserAffiliateLinks(affMap)
      }

      // Show error only if all auth requests failed
      const authResults = [configRes, connRes, affRes]
      if (authResults.every(r => r.status === 'rejected')) {
        setMessage(t('common.error'))
      }
    }
    load()
  }, [])

  const showMessage = (msg: string) => {
    setMessage(msg)
    setTimeout(() => setMessage(''), 3000)
  }

  const getForm = (ex: string): ExchangeKeyForm => keyForms[ex] || emptyForm()
  const updateForm = (ex: string, patch: Partial<ExchangeKeyForm>) =>
    setKeyForms((prev) => ({ ...prev, [ex]: { ...getForm(ex), ...patch } }))

  const getConn = (ex: string) => connections.find((c) => c.exchange_type === ex)

  // ── Save Handlers ──

  const saveLiveKeys = async (exchangeType: string) => {
    const form = getForm(exchangeType)
    setSaving(true)
    try {
      await api.put(`/config/exchange-connections/${exchangeType}`, {
        api_key: form.apiKey, api_secret: form.apiSecret, passphrase: form.passphrase,
      })
      const res = await api.get('/config/exchange-connections')
      setConnections(res.data.connections || [])
      updateForm(exchangeType, { apiKey: '', apiSecret: '', passphrase: '' })
      showMessage(t('settings.saved'))
      // After saving HL credentials, show inline setup section
      if (exchangeType === 'hyperliquid') {
        setHlSetupVisible(true)
        loadHlReferralInfo()
      }
    } catch (err) { showMessage(getApiErrorMessage(err, t('common.saveFailed'))) }
    setSaving(false)
  }

  const saveDemoKeys = async (exchangeType: string) => {
    const form = getForm(exchangeType)
    setSaving(true)
    try {
      await api.put(`/config/exchange-connections/${exchangeType}`, {
        demo_api_key: form.demoApiKey, demo_api_secret: form.demoApiSecret, demo_passphrase: form.demoPassphrase,
      })
      const res = await api.get('/config/exchange-connections')
      setConnections(res.data.connections || [])
      updateForm(exchangeType, { demoApiKey: '', demoApiSecret: '', demoPassphrase: '' })
      showMessage(t('settings.saved'))
    } catch (err) { showMessage(getApiErrorMessage(err, t('common.saveFailed'))) }
    setSaving(false)
  }

  const testConnection = async (exchangeType: string, mode: 'live' | 'demo') => {
    try {
      const res = await api.post(`/config/exchange-connections/${exchangeType}/test?mode=${mode}`)
      const modeLabel = mode === 'demo' ? t('common.demo') : t('common.live')
      showMessage(t('settings.testConnectionResult', { mode: modeLabel, exchange: exchangeType, balance: res.data.balance }))
    } catch (err) { showMessage(getApiErrorMessage(err, t('settings.connectionFailed'))) }
  }

  const loadConnectionStatus = async () => {
    setConnLoading(true)
    try {
      const res = await api.get('/config/connections')
      setConnStatus(res.data)
    } catch (err) { showMessage(getApiErrorMessage(err, t('common.loadError', 'Failed to load data'))) }
    setConnLoading(false)
  }

  const loadHlRevenue = async () => {
    setHlLoading(true)
    try {
      const res = await api.get('/config/hyperliquid/revenue-summary')
      setHlRevenue(res.data)
    } catch { /* HL not configured - OK */ }
    setHlLoading(false)
  }

  const loadHlAdminSettings = async () => {
    try {
      const res = await api.get('/config/hyperliquid/admin-settings')
      setHlAdminSettings(res.data)
      setHlAdminForm({
        builder_address: res.data.builder_address || '',
        builder_fee: res.data.builder_fee || 10,
        referral_code: res.data.referral_code || '',
      })
    } catch { /* not admin or not available */ }
  }

  const saveHlAdminSettings = async () => {
    setHlAdminSaving(true)
    try {
      await api.put('/config/hyperliquid/admin-settings', hlAdminForm)
      showMessage(t('settings.hlSettingsSaved'))
      await loadHlAdminSettings()
      // Refresh revenue view too
      loadHlRevenue()
    } catch (err) {
      showMessage(getApiErrorMessage(err, t('settings.hlSettingsFailed')))
    }
    setHlAdminSaving(false)
  }

  const loadAffiliateLinks = async () => {
    try {
      const res = await api.get('/affiliate-links')
      const map: typeof affiliateLinks = {}
      for (const link of res.data) {
        map[link.exchange_type] = { affiliate_url: link.affiliate_url, label: link.label || '', is_active: link.is_active }
      }
      setAffiliateLinks(map)
      // Pre-fill forms
      const forms: typeof affiliateForms = {}
      for (const ex of ['bitget', 'weex', 'hyperliquid', 'bitunix', 'bingx']) {
        const existing = map[ex]
        const existingRaw = res.data.find((l: any) => l.exchange_type === ex)
        forms[ex] = { url: existing?.affiliate_url || '', label: existing?.label || '', active: existing?.is_active ?? true, uidRequired: existingRaw?.uid_required || false }
      }
      setAffiliateForms(forms)
      setAffiliateLoaded(true)
    } catch (err) { console.error('Failed to load affiliate links:', err); useToastStore.getState().addToast('error', t('common.loadError', 'Failed to load data')) }
  }

  const saveAffiliateLink = async (exchange: string) => {
    const form = affiliateForms[exchange]
    if (!form?.url) return
    setSaving(true)
    try {
      await api.put(`/affiliate-links/${exchange}`, {
        affiliate_url: form.url,
        label: form.label || null,
        is_active: form.active,
        uid_required: form.uidRequired,
      })
      showMessage(t('settings.saved'))
      loadAffiliateLinks()
    } catch (err) { showMessage(getApiErrorMessage(err, t('common.saveFailed'))) }
    setSaving(false)
  }

  const saveAllAffiliateLinks = async () => {
    const exchanges = Object.entries(affiliateForms).filter(([, form]) => form.url)
    if (exchanges.length === 0) return
    setSaving(true)
    try {
      await Promise.all(exchanges.map(([ex, form]) =>
        api.put(`/affiliate-links/${ex}`, {
          affiliate_url: form.url,
          label: form.label || null,
          is_active: form.active,
          uid_required: form.uidRequired,
        })
      ))
      showMessage(t('settings.saved'))
      loadAffiliateLinks()
    } catch (err) { showMessage(getApiErrorMessage(err, t('common.saveFailed'))) }
    setSaving(false)
  }

  const deleteAffiliateLink = async (exchange: string) => {
    setSaving(true)
    try {
      await api.delete(`/affiliate-links/${exchange}`)
      showMessage(t('settings.saved'))
      loadAffiliateLinks()
    } catch (err) { showMessage(getApiErrorMessage(err, t('common.saveFailed'))) }
    setSaving(false)
  }

  const saveAffiliateUid = async (exchangeType: string) => {
    const uid = uidForms[exchangeType]?.trim()
    if (!uid) return
    setSaving(true)
    try {
      const res = await api.put(`/config/exchange-connections/${exchangeType}/affiliate-uid`, { uid })
      const connRes = await api.get('/config/exchange-connections')
      setConnections(connRes.data.connections || [])
      setUidForms(prev => ({ ...prev, [exchangeType]: '' }))
      showMessage(res.data.verified ? t('affiliate.uidVerified') : t('affiliate.uidSaved'))
    } catch (err) {
      showMessage(getApiErrorMessage(err, t('common.error')))
    }
    setSaving(false)
  }

  const loadHlReferralInfo = async () => {
    try {
      const res = await api.get('/config/hyperliquid/builder-config')
      setHlReferralInfo(res.data)
    } catch { /* ignore — no HL connection */ }
  }

  const loadAdminUids = async (page = adminUidPage, search = adminUidSearch, status = adminUidFilter) => {
    try {
      const res = await api.get('/config/admin/affiliate-uids', { params: { page, per_page: 15, search, status } })
      setAdminUids(res.data.items)
      setAdminUidTotal(res.data.total)
      setAdminUidPages(res.data.pages)
      setAdminUidPage(res.data.page)
      setAdminUidStats(res.data.stats)
    } catch {}
  }

  const verifyAdminUid = async (connectionId: number, verified: boolean) => {
    try {
      await api.put(`/config/admin/affiliate-uids/${connectionId}/verify`, { verified })
      await loadAdminUids(adminUidPage, adminUidSearch, adminUidFilter)
      showMessage(verified ? t('affiliate.uidVerified') : t('affiliate.uidRejected'))
    } catch (err) {
      showMessage(getApiErrorMessage(err, t('common.error')))
    }
  }

  // Load HL referral info when HL accordion opens + auto-show setup if credentials exist
  useEffect(() => {
    if (openExchange === 'hyperliquid') {
      if (!hlReferralInfo) loadHlReferralInfo()
      // Show setup section if HL credentials are already configured
      const hlConn = getConn('hyperliquid')
      if (hlConn?.api_keys_configured) setHlSetupVisible(true)
    }
  }, [openExchange])

  useEffect(() => {
    if (activeTab === 'connections' && !connStatus) {
      loadConnectionStatus()
    }
    if (activeTab === 'hyperliquid' && !hlRevenue) {
      loadHlRevenue()
    }
    if (activeTab === 'affiliateLinks' && !affiliateLoaded) {
      loadAffiliateLinks()
      loadAdminUids()
    }
  }, [activeTab])

  useEffect(() => {
    if (activeTab === 'hyperliquid' && isAdmin) {
      loadHlAdminSettings()
      loadHlRevenue()
    }
  }, [activeTab])

  const groupServices = (services: Record<string, ServiceStatus>) => {
    const groups: Record<string, [string, ServiceStatus][]> = {
      data_source: [], exchange: [], notification: [],
    }
    for (const [key, svc] of Object.entries(services)) {
      const group = groups[svc.type]
      if (group) group.push([key, svc])
    }
    return groups
  }

  const circuitLabel = (state: string) => {
    if (state === 'closed') return t('settings.circuitClosed')
    if (state === 'open') return t('settings.circuitOpen')
    return t('settings.circuitHalfOpen')
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-white">{t('settings.title')}</h1>
        <TourHelpButton tourId="settings" />
      </div>

      {message && (
        <div className="mb-4 p-3 bg-emerald-500/10 dark:bg-primary-900/30 border border-emerald-500/20 dark:border-primary-800 rounded text-emerald-700 dark:text-primary-400 text-sm">
          {message}
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1 mb-6 bg-gray-900 p-1 rounded-lg w-fit overflow-x-auto max-w-full" data-tour="settings-tabs">
        {TABS.map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-2 sm:px-4 py-2 text-xs sm:text-sm rounded whitespace-nowrap ${
              activeTab === tab
                ? 'bg-primary-600 text-white'
                : 'text-gray-400 hover:text-white'
            }`}
          >
            {t(`settings.${tab}`)}
          </button>
        ))}
      </div>

      {/* API Keys Tab — Accordion */}
      {activeTab === 'apiKeys' && (() => {
        const liveCount = exchanges.filter(ex => getConn(ex.name)?.api_keys_configured).length
        const demoCount = exchanges.filter(ex => getConn(ex.name)?.demo_api_keys_configured).length
        const totalConfigured = liveCount + demoCount
        const totalPossible = exchanges.length + exchanges.filter(ex => ex.supports_demo).length
        const configPct = totalPossible > 0 ? Math.round((totalConfigured / totalPossible) * 100) : 0
        return (
          <div className="space-y-6" data-tour="settings-api-keys">
            {/* ── Summary Bar ── */}
            <div className="border border-white/10 bg-white/[0.03] rounded-xl p-5">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                <div className="flex items-center gap-4">
                  <div className={`w-12 h-12 rounded-xl flex items-center justify-center ${
                    liveCount === exchanges.length ? 'bg-emerald-500/10 dark:bg-emerald-500/15' : liveCount > 0 ? 'bg-yellow-500/10 dark:bg-yellow-500/15' : 'bg-gray-100 dark:bg-white/5'
                  }`}>
                    <Zap size={22} className={
                      liveCount === exchanges.length ? 'text-emerald-400' : liveCount > 0 ? 'text-yellow-400' : 'text-gray-600'
                    } />
                  </div>
                  <div>
                    <h3 className="text-white font-semibold text-lg leading-tight">
                      {t('settings.apiKeys')}
                    </h3>
                    <p className="text-gray-500 text-sm mt-0.5">
                      {liveCount}/{exchanges.length} Live
                      {demoCount > 0 && <> &middot; {demoCount} Demo</>}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <div className="w-24 h-2 bg-white/5 rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full transition-all duration-500 ${
                        liveCount === exchanges.length ? 'bg-emerald-500' : liveCount > 0 ? 'bg-yellow-500' : 'bg-gray-600'
                      }`}
                      style={{ width: `${configPct}%` }}
                    />
                  </div>
                  <span className={`text-sm font-bold tabular-nums ${
                    liveCount === exchanges.length ? 'text-emerald-400' : liveCount > 0 ? 'text-yellow-400' : 'text-gray-600'
                  }`}>
                    {configPct}%
                  </span>
                </div>
              </div>
            </div>

            {/* ── Exchange Cards ── */}
            <div className="space-y-3 max-w-2xl">
              {exchanges.map((ex, exIdx) => {
                const conn = getConn(ex.name)
                const form = getForm(ex.name)
                const showPass = ex.requires_passphrase
                const isOpen = openExchange === ex.name
                const liveOk = conn?.api_keys_configured ?? false
                const demoOk = conn?.demo_api_keys_configured ?? false

                return (
                  <div key={ex.name} className="border border-white/[0.08] bg-white/[0.02] rounded-xl overflow-hidden" {...(exIdx === 0 ? { 'data-tour': 'settings-test-conn' } : {})}>
                    {/* Accordion Header with accent */}
                    <button
                      onClick={() => setOpenExchange(isOpen ? null : ex.name)}
                      className="w-full flex items-center justify-between px-5 py-3.5 hover:bg-white/[0.04] transition-colors"
                    >
                      <div className="flex items-center gap-3">
                        <div className={`w-9 h-9 rounded-lg flex items-center justify-center ${
                          liveOk ? 'bg-emerald-500/10' : 'bg-white/5'
                        }`}>
                          <ExchangeIcon exchange={ex.name} size={20} />
                        </div>
                        <div className="text-left">
                          <h3 className="text-white font-semibold text-sm">{ex.display_name}</h3>
                          {liveOk && (
                            <span className="text-[10px] text-gray-600">{ex.auth_type === 'eth_wallet' ? 'Wallet' : 'API'}</span>
                          )}
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        {liveOk && (
                          <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400">
                            Live
                          </span>
                        )}
                        {demoOk && (
                          <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-yellow-500/10 text-yellow-400">
                            Demo
                          </span>
                        )}
                        {!liveOk && !demoOk && (
                          <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-white/5 text-gray-500">
                            {t('settings.notConfigured')}
                          </span>
                        )}
                        <ChevronDown size={14} className={`text-gray-500 transition-transform ${isOpen ? 'rotate-180' : ''}`} />
                      </div>
                    </button>

                    {/* Accordion Content */}
                    {isOpen && (
                      <div className="px-5 pb-5 pt-1 space-y-5 border-t border-white/[0.06]">
                        <KeyForm
                          label={ex.auth_type === 'eth_wallet' ? t('settings.mainnet') : t('common.live')}
                          configured={liveOk}
                          keyValue={form.apiKey} secretValue={form.apiSecret} passphraseValue={form.passphrase}
                          onKeyChange={(v) => updateForm(ex.name, { apiKey: v })}
                          onSecretChange={(v) => updateForm(ex.name, { apiSecret: v })}
                          onPassphraseChange={(v) => updateForm(ex.name, { passphrase: v })}
                          onSave={() => saveLiveKeys(ex.name)}
                          onTest={() => testConnection(ex.name, 'live')}
                          saving={saving} t={t} showPassphrase={showPass} authType={ex.auth_type}
                        />

                        {ex.supports_demo && (
                          <>
                            <div className="border-t border-white/[0.06] my-2" />
                            <KeyForm
                              label={ex.auth_type === 'eth_wallet' ? t('settings.testnet') : t('common.demo')}
                              configured={demoOk}
                              keyValue={form.demoApiKey} secretValue={form.demoApiSecret} passphraseValue={form.demoPassphrase}
                              onKeyChange={(v) => updateForm(ex.name, { demoApiKey: v })}
                              onSecretChange={(v) => updateForm(ex.name, { demoApiSecret: v })}
                              onPassphraseChange={(v) => updateForm(ex.name, { demoPassphrase: v })}
                              onSave={() => saveDemoKeys(ex.name)}
                              onTest={() => testConnection(ex.name, 'demo')}
                              saving={saving} t={t} showPassphrase={showPass} authType={ex.auth_type}
                            />
                            {ex.auth_type === 'eth_wallet' && (
                              <div className="p-2.5 bg-amber-900/20 border border-amber-800/40 rounded-lg text-xs text-amber-300">
                                {t('settings.hyperliquidTestnetNote')}
                              </div>
                            )}
                          </>
                        )}

                        {/* Hyperliquid: Inline setup (affiliate + builder fee) — hidden for admins */}
                        {ex.name === 'hyperliquid' && hlSetupVisible && !isAdmin && (
                          <HyperliquidSetup onComplete={() => loadHlReferralInfo()} />
                        )}

                        {/* Bitget/Weex: Affiliate UID */}
                        {ex.name !== 'hyperliquid' && userAffiliateLinks[ex.name]?.uid_required && (
                          <div className="mt-4 pt-4 border-t border-white/[0.06]">
                            <h4 className="text-sm font-medium text-white mb-2">{t('affiliate.uid')}</h4>
                            <p className="text-gray-400 text-xs mb-3">{t('affiliate.uidHint')}</p>
                            {userAffiliateLinks[ex.name]?.affiliate_url && (
                              <div className="mb-3 p-3 bg-emerald-500/[0.05] border border-emerald-500/20 rounded-lg">
                                <p className="text-gray-400 text-xs mb-1">{userAffiliateLinks[ex.name]?.label || t('bots.affiliateLink')}</p>
                                <a href={userAffiliateLinks[ex.name].affiliate_url} target="_blank" rel="noopener noreferrer"
                                   className="text-emerald-400 hover:text-emerald-300 break-all text-sm font-medium inline-flex items-center gap-1.5">
                                  <ExternalLink size={12} />
                                  {userAffiliateLinks[ex.name].affiliate_url}
                                </a>
                              </div>
                            )}
                            <div className="flex gap-2 items-end">
                              <div className="flex-1">
                                <input
                                  type="text"
                                  value={uidForms[ex.name] ?? getConn(ex.name)?.affiliate_uid ?? ''}
                                  onChange={(e) => setUidForms(prev => ({ ...prev, [ex.name]: e.target.value }))}
                                  placeholder={t('affiliate.uidPlaceholder')}
                                  className="filter-select w-full text-sm"
                                />
                              </div>
                              <button
                                onClick={() => saveAffiliateUid(ex.name)}
                                disabled={saving || !uidForms[ex.name]?.trim()}
                                className="px-3 py-1.5 text-xs bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50 transition-colors"
                              >
                                {t('affiliate.submitUid')}
                              </button>
                            </div>
                            {getConn(ex.name)?.affiliate_uid && (
                              <div className="mt-2">
                                {getConn(ex.name)?.affiliate_verified ? (
                                  <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400">
                                    {t('affiliate.uidVerified')}
                                  </span>
                                ) : (
                                  <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-yellow-500/10 text-yellow-400">
                                    {t('affiliate.uidPending')}
                                  </span>
                                )}
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>

          </div>
        )
      })()}

      {/* Affiliate Links Tab (admin only) */}
      {activeTab === 'affiliateLinks' && (() => {
        const AFFILIATE_EXCHANGES = ['bitget', 'weex', 'hyperliquid', 'bitunix', 'bingx']
        const configuredAff = AFFILIATE_EXCHANGES.filter(ex => !!affiliateLinks[ex]).length
        return (
          <div className="space-y-6">
            {/* ── Summary Bar ── */}
            <div className="border border-white/10 bg-white/[0.03] rounded-xl p-5">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                <div className="flex items-center gap-4">
                  <div className={`w-12 h-12 rounded-xl flex items-center justify-center ${
                    configuredAff === AFFILIATE_EXCHANGES.length ? 'bg-emerald-500/15' : configuredAff > 0 ? 'bg-yellow-500/15' : 'bg-white/5'
                  }`}>
                    <ExternalLink size={22} className={
                      configuredAff === AFFILIATE_EXCHANGES.length ? 'text-emerald-400' : configuredAff > 0 ? 'text-yellow-400' : 'text-gray-600'
                    } />
                  </div>
                  <div>
                    <h3 className="text-white font-semibold text-lg leading-tight">
                      {t('settings.affiliateLinks')}
                    </h3>
                    <p className="text-gray-500 text-sm mt-0.5">
                      {configuredAff}/{AFFILIATE_EXCHANGES.length} {t('settings.configured')}
                      {adminUidStats.pending > 0 && (
                        <> &middot; <span className="text-yellow-400">{adminUidStats.pending} {t('affiliate.uidPending')}</span></>
                      )}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  {/* UID Stats Badges */}
                  <div className="flex items-center gap-1.5">
                    <span className="flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded bg-white/5 text-gray-400 border border-white/[0.08]">
                      <Users size={10} /> {adminUidStats.total}
                    </span>
                    <span className="flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded bg-yellow-500/10 text-yellow-400 border border-yellow-500/20">
                      <Clock size={10} /> {adminUidStats.pending}
                    </span>
                    <span className="flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                      <CheckCircle size={10} /> {adminUidStats.verified}
                    </span>
                  </div>
                </div>
              </div>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.6fr)] gap-4 items-start">
              {/* Left: Affiliate Link Configuration */}
              <div>
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <ExternalLink size={16} className="text-gray-500" />
                    <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wider">
                      {t('settings.affiliateLinksDesc').split('.')[0]}
                    </h3>
                  </div>
                  <button
                    onClick={saveAllAffiliateLinks}
                    disabled={saving || !Object.values(affiliateForms).some(f => f.url)}
                    className="px-3 py-1.5 text-xs bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50 transition-colors flex items-center gap-1.5"
                  >
                    {t('settings.saveAll')}
                  </button>
                </div>
                <div className="space-y-3">
                  {AFFILIATE_EXCHANGES.map((ex) => {
                    const form = affiliateForms[ex] || { url: '', label: '', active: true }
                    const hasExisting = !!affiliateLinks[ex]
                    return (
                      <div key={ex} className="border border-white/[0.08] bg-white/[0.02] rounded-xl overflow-hidden">
                        {/* Exchange header — clickable to toggle */}
                        <div
                          className={`px-4 py-2.5 flex items-center justify-between cursor-pointer select-none ${
                            affiliateCardOpen[ex]
                              ? `border-b ${hasExisting ? 'border-emerald-500/10 bg-emerald-500/[0.03]' : 'border-white/[0.06] bg-white/[0.02]'}`
                              : hasExisting ? 'bg-emerald-500/[0.03]' : 'bg-white/[0.02]'
                          }`}
                          onClick={() => setAffiliateCardOpen(prev => ({ ...prev, [ex]: !prev[ex] }))}
                        >
                          <div className="flex items-center gap-2.5">
                            <ExchangeIcon exchange={ex} size={18} />
                            <span className="text-xs font-semibold text-gray-300 uppercase tracking-wider capitalize">{ex}</span>
                          </div>
                          <div className="flex items-center gap-2">
                            <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${
                              hasExisting ? 'bg-emerald-500/10 text-emerald-400' : 'bg-white/5 text-gray-500'
                            }`}>
                              {hasExisting ? t('settings.configured') : t('settings.notConfigured')}
                            </span>
                            <ChevronDown size={14} className={`text-gray-400 transition-transform duration-200 ${affiliateCardOpen[ex] ? 'rotate-180' : ''}`} />
                          </div>
                        </div>
                        {/* Collapsible form content */}
                        {affiliateCardOpen[ex] && (
                        <div className="p-4 space-y-3">
                          <div>
                            <label className="block text-xs text-gray-500 mb-1">{t('settings.affiliateUrl')}</label>
                            <input
                              type="text"
                              value={form.url}
                              onChange={(e) => setAffiliateForms(prev => ({ ...prev, [ex]: { ...form, url: e.target.value } }))}
                              placeholder="https://..."
                              className="filter-select w-full text-sm"
                            />
                          </div>
                          <div>
                            <label className="block text-xs text-gray-500 mb-1">{t('settings.affiliateLabel')}</label>
                            <input
                              type="text"
                              value={form.label}
                              onChange={(e) => setAffiliateForms(prev => ({ ...prev, [ex]: { ...form, label: e.target.value } }))}
                              placeholder={t('settings.affiliateLabelPlaceholder')}
                              className="filter-select w-full text-sm"
                            />
                          </div>
                          <div className="flex items-center gap-4">
                            <div className="flex items-center gap-2">
                              <input
                                type="checkbox"
                                id={`aff-active-${ex}`}
                                checked={form.active}
                                onChange={(e) => setAffiliateForms(prev => ({ ...prev, [ex]: { ...form, active: e.target.checked } }))}
                                className="rounded border-white/10 bg-white/5 text-primary-600"
                              />
                              <label htmlFor={`aff-active-${ex}`} className="text-xs text-gray-400">{t('settings.affiliateActive')}</label>
                            </div>
                            {ex !== 'hyperliquid' && (
                              <div className="flex items-center gap-2">
                                <input
                                  type="checkbox"
                                  id={`aff-uid-${ex}`}
                                  checked={form.uidRequired}
                                  onChange={(e) => setAffiliateForms(prev => ({ ...prev, [ex]: { ...form, uidRequired: e.target.checked } }))}
                                  className="rounded border-white/10 bg-white/5 text-primary-600"
                                />
                                <label htmlFor={`aff-uid-${ex}`} className="text-xs text-gray-400">{t('affiliate.uidRequiredToggle')}</label>
                              </div>
                            )}
                          </div>
                          <div className="flex gap-2 pt-1">
                            <button
                              onClick={() => saveAffiliateLink(ex)}
                              disabled={saving || !form.url}
                              className="px-3 py-1.5 text-xs bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50 transition-colors"
                            >
                              {t('settings.save')}
                            </button>
                            {hasExisting && (
                              <button
                                onClick={() => deleteAffiliateLink(ex)}
                                disabled={saving}
                                className="px-3 py-1.5 text-xs bg-red-500/10 text-red-400 border border-red-500/20 rounded-lg hover:bg-red-500/20 disabled:opacity-50 transition-colors"
                              >
                                {t('common.delete', 'Delete')}
                              </button>
                            )}
                          </div>
                        </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              </div>

              {/* Right: Admin UID Management — Paginated */}
              <div className="lg:sticky lg:top-4">
                <div className="flex items-center gap-2 mb-3">
                  <Users size={16} className="text-gray-500" />
                  <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wider">
                    {t('affiliate.affiliateUids')}
                  </h3>
                  <span className="text-xs px-2 py-0.5 rounded-full bg-white/5 text-gray-500 border border-white/[0.08] tabular-nums">
                    {adminUidStats.total}
                  </span>
                  {adminUidStats.pending > 0 && (
                    <span className="text-[10px] px-2 py-0.5 rounded-full bg-yellow-500/10 text-yellow-400 border border-yellow-500/20 tabular-nums animate-pulse">
                      {adminUidStats.pending} offen
                    </span>
                  )}
                </div>
                <div className="border border-white/[0.08] bg-white/[0.02] rounded-xl overflow-hidden">
                  {/* Search + Filter header */}
                  <div className="px-4 py-3 border-b border-white/[0.06] bg-white/[0.02]">
                    <div className="flex items-center gap-2">
                      <div className="relative flex-1">
                        <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-500" />
                        <input
                          type="text"
                          value={adminUidSearch}
                          onChange={(e) => {
                            setAdminUidSearch(e.target.value)
                            loadAdminUids(1, e.target.value, adminUidFilter)
                          }}
                          placeholder="Username / UID..."
                          className="filter-select w-full text-sm !pl-8"
                        />
                      </div>
                      <div className="flex rounded-lg border border-white/[0.08] overflow-hidden shrink-0">
                        {(['all', 'pending', 'verified'] as const).map(f => (
                          <button key={f} onClick={() => { setAdminUidFilter(f); loadAdminUids(1, adminUidSearch, f) }}
                            className={`px-2.5 py-1.5 text-xs transition-colors ${adminUidFilter === f ? 'bg-white/10 text-white' : 'text-gray-500 hover:text-gray-300'}`}>
                            {f === 'all' ? 'Alle' : f === 'pending' ? 'Offen' : 'Verifiziert'}
                          </button>
                        ))}
                      </div>
                    </div>
                  </div>

                  {/* Table */}
                  {adminUids.length === 0 ? (
                    <div className="py-8 text-center">
                      <Users size={20} className="text-gray-700 mx-auto mb-2" />
                      <p className="text-gray-500 text-xs">{t('affiliate.noUids')}</p>
                    </div>
                  ) : (
                    <div className="overflow-x-auto">
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="border-b border-white/[0.06] text-gray-400 text-[10px] uppercase tracking-wider">
                            <th className="text-left py-2.5 px-3 font-medium">{t('admin.users', 'User')}</th>
                            <th className="text-left py-2.5 px-3 font-medium">UID</th>
                            <th className="text-left py-2.5 px-3 font-medium">{t('affiliate.submittedAt')}</th>
                            <th className="text-left py-2.5 px-3 font-medium">{t('affiliate.status', 'Status')}</th>
                            <th className="text-right py-2.5 px-3 font-medium">{t('affiliate.action', 'Action')}</th>
                          </tr>
                        </thead>
                        <tbody>
                          {adminUids.map((item) => {
                            const isPending = !item.affiliate_verified
                            const isManual = item.verify_method === 'manual'
                            const needsAttention = isPending && isManual
                            return (
                            <tr key={item.connection_id} className={`border-b transition-colors ${
                              needsAttention
                                ? 'border-yellow-500/10 bg-yellow-500/[0.03] hover:bg-yellow-500/[0.06]'
                                : isPending
                                  ? 'border-white/[0.04] bg-white/[0.01] hover:bg-white/[0.03]'
                                  : 'border-white/[0.04] hover:bg-white/[0.03]'
                            }`}>
                              <td className="py-2 px-3">
                                <div className="flex items-center gap-2">
                                  <ExchangeIcon exchange={item.exchange_type} size={20} />
                                  <div className="min-w-0">
                                    <div className="text-white text-xs font-medium truncate">{item.username}</div>
                                    <div className="text-gray-500 text-[10px] capitalize">{item.exchange_type}</div>
                                  </div>
                                </div>
                              </td>
                              <td className="py-2 px-3 text-gray-300 font-mono text-[10px]">{item.affiliate_uid}</td>
                              <td className="py-2 px-3 text-gray-500 text-[10px] whitespace-nowrap tabular-nums">
                                {item.submitted_at
                                  ? new Date(item.submitted_at).toLocaleDateString(undefined, { day: '2-digit', month: '2-digit', year: 'numeric' })
                                  : '—'}
                              </td>
                              <td className="py-2 px-3">
                                <div className="flex flex-col gap-0.5">
                                  <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded inline-block w-fit ${
                                    item.affiliate_verified
                                      ? 'bg-emerald-500/10 text-emerald-400'
                                      : needsAttention
                                        ? 'bg-orange-500/10 text-orange-400'
                                        : 'bg-yellow-500/10 text-yellow-400'
                                  }`}>
                                    {item.affiliate_verified
                                      ? t('affiliate.uidVerified')
                                      : needsAttention
                                        ? t('affiliate.pendingManual')
                                        : t('affiliate.uidPending')}
                                  </span>
                                  {isPending && isManual && (
                                    <span className="text-[9px] text-orange-400/60">{t('affiliate.manualHint')}</span>
                                  )}
                                  {isPending && !isManual && (
                                    <span className="text-[9px] text-yellow-400/60">{t('affiliate.autoFailed')}</span>
                                  )}
                                </div>
                              </td>
                              <td className="py-2 px-3 text-right">
                                <div className="flex gap-1 justify-end">
                                  {isPending && (
                                    <button onClick={() => verifyAdminUid(item.connection_id, true)}
                                      title={t('affiliate.verifyUid')}
                                      className="px-2 py-0.5 text-[10px] bg-emerald-500/10 text-emerald-400 rounded hover:bg-emerald-500/20 transition-colors">
                                      {t('affiliate.verifyUid')}
                                    </button>
                                  )}
                                  <button onClick={() => verifyAdminUid(item.connection_id, false)}
                                    title={t('affiliate.rejectUid')}
                                    className={`px-2 py-0.5 text-[10px] rounded transition-colors ${
                                      item.affiliate_verified
                                        ? 'bg-red-500/10 text-red-400 hover:bg-red-500/20'
                                        : 'bg-red-500/5 text-red-400/60 hover:bg-red-500/10'
                                    }`}>
                                    {t('affiliate.rejectUid')}
                                  </button>
                                </div>
                              </td>
                            </tr>
                            )
                          })}
                        </tbody>
                      </table>
                    </div>
                  )}

                  {/* Pagination */}
                  {adminUidPages > 1 && (
                    <div className="px-4 py-3 border-t border-white/[0.06] flex items-center justify-between">
                      <span className="text-[10px] text-gray-600 tabular-nums">{adminUidTotal} Ergebnisse</span>
                      <Pagination
                        page={adminUidPage}
                        totalPages={adminUidPages}
                        onPageChange={loadAdminUids}
                      />
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        )
      })()}

      {/* Hyperliquid Tab */}
      {activeTab === 'hyperliquid' && (
        <div className="space-y-6">
          {/* ── Status Overview Bar ── */}
          {hlRevenue ? (() => {
            const builderOk = hlRevenue.builder?.configured && hlRevenue.builder?.user_approved
            const referralOk = hlRevenue.referral?.configured && hlRevenue.referral?.user_referred
            const statusCount = (builderOk ? 1 : 0) + (referralOk ? 1 : 0)
            const statusPct = Math.round((statusCount / 2) * 100)
            return (
              <div className="border border-white/10 bg-white/[0.03] rounded-xl p-5">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                  <div className="flex items-center gap-4">
                    <div className={`w-12 h-12 rounded-xl flex items-center justify-center ${
                      statusPct === 100 ? 'bg-emerald-500/15' : statusPct >= 50 ? 'bg-yellow-500/15' : 'bg-red-500/15'
                    }`}>
                      {statusPct === 100
                        ? <CheckCircle size={22} className="text-emerald-400" />
                        : statusPct >= 50
                          ? <Settings2 size={22} className="text-yellow-400" />
                          : <Shield size={22} className="text-red-400" />
                      }
                    </div>
                    <div>
                      <h3 className="text-white font-semibold text-lg leading-tight">
                        {statusPct === 100
                          ? t('settings.hlAllConfigured', 'Vollständig konfiguriert')
                          : statusPct >= 50
                            ? t('settings.hlPartialConfig', 'Teilweise konfiguriert')
                            : t('settings.hlNotReady', 'Einrichtung erforderlich')
                        }
                      </h3>
                      <p className="text-gray-500 text-sm mt-0.5">
                        {statusCount}/2 {t('settings.hlServicesActive', 'Dienste aktiv')}
                        {hlRevenue.earnings && (
                          <> &middot; ${(hlRevenue.earnings.total_builder_fees_30d || 0).toFixed(4)} (30d)</>
                        )}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <div className="flex items-center gap-2">
                      <div className="w-24 h-2 bg-white/5 rounded-full overflow-hidden">
                        <div
                          className={`h-full rounded-full transition-all duration-500 ${
                            statusPct === 100 ? 'bg-emerald-500' : statusPct >= 50 ? 'bg-yellow-500' : 'bg-red-500'
                          }`}
                          style={{ width: `${statusPct}%` }}
                        />
                      </div>
                      <span className={`text-sm font-bold tabular-nums ${
                        statusPct === 100 ? 'text-emerald-400' : statusPct >= 50 ? 'text-yellow-400' : 'text-red-400'
                      }`}>
                        {statusPct}%
                      </span>
                    </div>
                    <button onClick={loadHlRevenue} disabled={hlLoading}
                      className="px-3 py-1.5 text-sm bg-white/5 border border-white/10 text-gray-300 rounded-xl hover:bg-white/10 disabled:opacity-50 transition-colors">
                      {hlLoading ? t('settings.refreshing') : t('settings.refreshStatus')}
                    </button>
                  </div>
                </div>
              </div>
            )
          })() : (
            <div className="border border-white/10 bg-white/[0.03] rounded-xl p-5">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                <div className="flex items-center gap-4">
                  <div className="w-12 h-12 rounded-xl bg-white/5 flex items-center justify-center">
                    <Settings2 size={22} className="text-gray-600" />
                  </div>
                  <div>
                    <h3 className="text-white font-semibold text-lg leading-tight">Hyperliquid</h3>
                    <p className="text-gray-500 text-sm mt-0.5">{hlLoading ? t('settings.refreshing') : t('settings.hlNoConnection')}</p>
                  </div>
                </div>
                {!hlLoading && (
                  <button onClick={loadHlRevenue}
                    className="px-4 py-2 text-sm bg-primary-600 text-white rounded-xl hover:bg-primary-700 transition-colors">
                    {t('settings.refreshStatus')}
                  </button>
                )}
              </div>
            </div>
          )}

          {/* ── Earnings ── */}
          {hlRevenue?.earnings && (
            <div>
              <div className="flex items-center gap-2 mb-3">
                <DollarSign size={16} className="text-gray-500" />
                <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wider">
                  {t('settings.hlEarnings')}
                </h3>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <div className="border border-white/[0.08] bg-white/[0.02] rounded-xl p-4 hover:bg-white/[0.04] transition-colors">
                  <p className="text-[10px] text-gray-400 uppercase tracking-wider mb-1">{t('settings.hlBuilderFees30d')}</p>
                  <p className="text-xl font-bold text-emerald-400 tabular-nums">
                    ${(hlRevenue.earnings.total_builder_fees_30d || 0).toFixed(4)}
                  </p>
                </div>
                <div className="border border-white/[0.08] bg-white/[0.02] rounded-xl p-4 hover:bg-white/[0.04] transition-colors">
                  <p className="text-[10px] text-gray-400 uppercase tracking-wider mb-1">{t('settings.hlTradesWithFee')}</p>
                  <p className="text-xl font-bold text-white tabular-nums">
                    {hlRevenue.earnings.trades_with_builder_fee || 0}
                  </p>
                </div>
                <div className="border border-white/[0.08] bg-white/[0.02] rounded-xl p-4 hover:bg-white/[0.04] transition-colors">
                  <p className="text-[10px] text-gray-400 uppercase tracking-wider mb-1">{t('settings.hlMonthlyEstimate')}</p>
                  <p className="text-xl font-bold text-emerald-400 tabular-nums">
                    ${(hlRevenue.earnings.monthly_estimate || 0).toFixed(2)}
                    <span className="text-xs text-gray-500 font-normal ml-0.5">/mo</span>
                  </p>
                </div>
              </div>
            </div>
          )}

          {/* ── Admin Configuration ── */}
          <div>
            <div className="flex items-center gap-2 mb-3">
              <Settings2 size={16} className="text-gray-500" />
              <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wider">
                {t('settings.hlBuilderConfig')}
              </h3>
            </div>
            <div className="border border-white/[0.08] bg-white/[0.02] rounded-xl">
              <div className="px-4 py-2.5 border-b border-white/[0.06] bg-white/[0.02] rounded-t-xl">
                <p className="text-xs text-gray-500">{t('settings.hlBuilderConfigDesc')}</p>
              </div>
              <div className="p-4 space-y-4">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-xs text-gray-500 mb-1.5">{t('settings.hlBuilderAddress')}</label>
                    <input
                      type="text"
                      value={hlAdminForm.builder_address}
                      onChange={(e) => setHlAdminForm(prev => ({ ...prev, builder_address: e.target.value }))}
                      placeholder="0x..."
                      className="filter-select w-full text-sm font-mono"
                    />
                    {hlAdminSettings?.sources?.builder_address && (
                      <p className="text-[10px] text-gray-600 mt-1">
                        {t('settings.hlSource', { source: hlAdminSettings.sources.builder_address === 'db' ? t('settings.hlSourceDb') : hlAdminSettings.sources.builder_address === 'env' ? t('settings.hlSourceEnv') : t('settings.hlSourceNotSet') })}
                      </p>
                    )}
                  </div>
                  <div>
                    <label className="block text-xs text-gray-500 mb-1.5">{t('settings.hlBuilderFeeLabel')}</label>
                    <FilterDropdown
                      value={String(hlAdminForm.builder_fee)}
                      onChange={val => setHlAdminForm(prev => ({ ...prev, builder_fee: parseInt(val) }))}
                      options={[
                        { value: '0', label: t('settings.hlFeeDisabled') },
                        { value: '1', label: '1 (0.001%)' },
                        { value: '5', label: '5 (0.005%)' },
                        { value: '10', label: `10 (0.01%) - ${t('settings.hlFeeDefault')}` },
                        { value: '25', label: '25 (0.025%)' },
                        { value: '50', label: '50 (0.05%)' },
                        { value: '100', label: '100 (0.1%)' },
                      ]}
                      ariaLabel="Builder Fee"
                    />
                    {hlAdminSettings?.sources?.builder_fee && (
                      <p className="text-[10px] text-gray-600 mt-1">
                        {t('settings.hlSource', { source: hlAdminSettings.sources.builder_fee === 'db' ? t('settings.hlSourceDb') : hlAdminSettings.sources.builder_fee === 'env' ? t('settings.hlSourceEnv') : t('settings.hlSourceNotSet') })}
                      </p>
                    )}
                  </div>
                </div>
                <div className="sm:w-1/2">
                  <label className="block text-xs text-gray-500 mb-1.5">{t('settings.hlReferralCode')}</label>
                  <input
                    type="text"
                    value={hlAdminForm.referral_code}
                    onChange={(e) => setHlAdminForm(prev => ({ ...prev, referral_code: e.target.value }))}
                    placeholder="e.g. MYCODE"
                    className="filter-select w-full text-sm"
                  />
                  {hlAdminSettings?.sources?.referral_code && (
                    <p className="text-[10px] text-gray-600 mt-1">
                      {t('settings.hlSource', { source: hlAdminSettings.sources.referral_code === 'db' ? t('settings.hlSourceDb') : hlAdminSettings.sources.referral_code === 'env' ? t('settings.hlSourceEnv') : t('settings.hlSourceNotSet') })}
                    </p>
                  )}
                </div>
                <div className="pt-1">
                  <button
                    onClick={saveHlAdminSettings}
                    disabled={hlAdminSaving}
                    className="px-4 py-2 text-sm bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50 transition-colors"
                  >
                    {hlAdminSaving ? t('settings.hlSaving') : t('settings.hlSaveSettings')}
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Connections Tab */}
      {activeTab === 'connections' && (
        <div className="space-y-6">
          {connStatus ? (() => {
            const groups = groupServices(connStatus.services)
            const CAT_ICONS: Record<string, typeof Activity> = {
              sentiment: TrendingUp,
              futures: BarChart3,
              options: Cpu,
              spot: Database,
              technical: Activity,
              tradfi: Zap,
            }
            const catLabels: Record<string, string> = {
              sentiment: t('settings.sentimentNews', 'Sentiment & News'),
              futures: t('settings.futuresData', 'Futures Data'),
              options: t('settings.optionsData', 'Options Data'),
              spot: t('settings.spotMarket', 'Spot Market'),
              technical: t('settings.technicalIndicators', 'Technical Indicators'),
              tradfi: t('settings.tradfiCme', 'TradFi / CME'),
            }
            const catOrder = ['sentiment', 'futures', 'options', 'spot', 'technical', 'tradfi']
            const dsItems = groups['data_source'] || []
            const exchItems = groups['exchange'] || []
            const notifItems = groups['notification'] || []
            const allItems = [...dsItems, ...exchItems, ...notifItems].filter(([, s]) => (s as any).configured !== false)
            const totalOnline = allItems.filter(([, s]) => s.reachable).length
            const totalCount = allItems.length
            const healthPct = totalCount > 0 ? Math.round((totalOnline / totalCount) * 100) : 0
            const cbEntries = Object.entries(connStatus.circuit_breakers)
            const cbHealthy = cbEntries.filter(([, cb]) => cb.state === 'closed').length

            return (
              <>
                {/* ── Health Summary Bar ── */}
                <div className="border border-white/10 bg-white/[0.03] rounded-xl p-5">
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                    <div className="flex items-center gap-4">
                      <div className={`w-12 h-12 rounded-xl flex items-center justify-center ${
                        healthPct === 100 ? 'bg-emerald-500/15' : healthPct >= 80 ? 'bg-yellow-500/15' : 'bg-red-500/15'
                      }`}>
                        {healthPct === 100
                          ? <Wifi size={22} className="text-emerald-400" />
                          : healthPct >= 80
                            ? <Activity size={22} className="text-yellow-400" />
                            : <WifiOff size={22} className="text-red-400" />
                        }
                      </div>
                      <div>
                        <h3 className="text-white font-semibold text-lg leading-tight">
                          {healthPct === 100 ? t('settings.allSystemsOperational', 'Alle Systeme betriebsbereit') : healthPct >= 80 ? t('settings.partialOutage', 'Teilweise eingeschränkt') : t('settings.majorOutage', 'Systemstörung')}
                        </h3>
                        <p className="text-gray-500 text-sm mt-0.5">
                          {totalOnline}/{totalCount} {t('settings.servicesOnline', 'Dienste online')}
                          {cbEntries.length > 0 && <> &middot; {cbHealthy}/{cbEntries.length} {t('settings.circuitBreakers')}</>}
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center gap-3">
                      <div className="flex items-center gap-2">
                        <div className="w-24 h-2 bg-white/5 rounded-full overflow-hidden">
                          <div
                            className={`h-full rounded-full transition-all duration-500 ${
                              healthPct === 100 ? 'bg-emerald-500' : healthPct >= 80 ? 'bg-yellow-500' : 'bg-red-500'
                            }`}
                            style={{ width: `${healthPct}%` }}
                          />
                        </div>
                        <span className={`text-sm font-bold tabular-nums ${
                          healthPct === 100 ? 'text-emerald-400' : healthPct >= 80 ? 'text-yellow-400' : 'text-red-400'
                        }`}>
                          {healthPct}%
                        </span>
                      </div>
                      <button onClick={loadConnectionStatus} disabled={connLoading}
                        className="px-3 py-1.5 text-sm bg-white/5 border border-white/10 text-gray-300 rounded-xl hover:bg-white/10 disabled:opacity-50 transition-colors">
                        {connLoading ? t('settings.refreshing') : t('settings.refreshStatus')}
                      </button>
                    </div>
                  </div>
                </div>

                {/* ── Data Sources ── */}
                {dsItems.length > 0 && (() => {
                  const byCategory: Record<string, [string, ServiceStatus][]> = {}
                  for (const [key, svc] of dsItems) {
                    const cat = (svc as any).category || 'other'
                    if (!byCategory[cat]) byCategory[cat] = []
                    byCategory[cat].push([key, svc])
                  }
                  const dsOnline = dsItems.filter(([, s]) => s.reachable).length
                  return (
                    <div>
                      <div className="flex items-center gap-3 mb-3">
                        <Database size={16} className="text-gray-500" />
                        <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wider">
                          {t('settings.dataSources')}
                        </h3>
                        <span className="text-xs px-2 py-0.5 rounded-full bg-white/5 text-gray-500 border border-white/10 tabular-nums">
                          {dsOnline}/{dsItems.length}
                        </span>
                      </div>
                      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
                        {catOrder.map(cat => {
                          const catItems = byCategory[cat]
                          if (!catItems || catItems.length === 0) return null
                          const catOnline = catItems.filter(([, s]) => s.reachable).length
                          const allUp = catOnline === catItems.length
                          const CatIcon = CAT_ICONS[cat] || Activity
                          return (
                            <div key={cat} className="border border-white/[0.08] bg-white/[0.02] rounded-xl overflow-hidden">
                              {/* Category header with accent */}
                              <div className={`px-4 py-2.5 flex items-center justify-between border-b ${
                                allUp ? 'border-emerald-500/10 bg-emerald-500/[0.03]' : 'border-red-500/10 bg-red-500/[0.03]'
                              }`}>
                                <div className="flex items-center gap-2">
                                  <CatIcon size={14} className={allUp ? 'text-emerald-400/70' : 'text-red-400/70'} />
                                  <span className="text-xs font-semibold text-gray-400 uppercase tracking-wider">
                                    {catLabels[cat] || cat}
                                  </span>
                                </div>
                                <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${
                                  allUp ? 'bg-emerald-500/10 text-emerald-400' : 'bg-red-500/10 text-red-400'
                                }`}>
                                  {catOnline}/{catItems.length}
                                </span>
                              </div>
                              {/* Items */}
                              <div className="px-3 py-2 space-y-0.5">
                                {catItems.map(([key, svc]) => (
                                  <div key={key} className="flex items-center justify-between py-1.5 px-1.5 rounded-lg hover:bg-white/[0.04] transition-colors">
                                    <div className="flex items-center gap-2.5 min-w-0">
                                      <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${svc.reachable ? 'bg-emerald-400' : 'bg-red-400'} ${svc.reachable ? '' : 'animate-pulse'}`} />
                                      <span className="text-white text-xs truncate">{svc.label}</span>
                                    </div>
                                    <div className="flex items-center gap-2 flex-shrink-0 ml-2">
                                      {(svc as any).provider && (svc as any).provider !== 'Calculated' && (
                                        <span className="text-gray-600 text-[10px] hidden sm:inline">{(svc as any).provider}</span>
                                      )}
                                      {svc.latency_ms != null && svc.latency_ms > 0 && (
                                        <span className={`text-[10px] tabular-nums px-1.5 py-0.5 rounded ${
                                          svc.latency_ms < 500 ? 'text-emerald-400/60' : svc.latency_ms < 2000 ? 'text-yellow-400/60' : 'text-red-400/60'
                                        }`}>
                                          {svc.latency_ms}ms
                                        </span>
                                      )}
                                    </div>
                                  </div>
                                ))}
                              </div>
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  )
                })()}

                {/* ── Exchanges & Notifications ── */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {exchItems.length > 0 && (
                    <div>
                      <div className="flex items-center gap-2 mb-3">
                        <Zap size={16} className="text-gray-500" />
                        <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wider">
                          {t('settings.exchangeApi')}
                        </h3>
                      </div>
                      <div className="space-y-2">
                        {exchItems.map(([key, svc]) => {
                          const isConfigured = (svc as any).configured !== false
                          return (
                            <div key={key} className="border border-white/[0.08] bg-white/[0.02] rounded-xl p-4 flex items-center justify-between hover:bg-white/[0.04] transition-colors">
                              <div className="flex items-center gap-3">
                                <div className={`w-9 h-9 rounded-lg flex items-center justify-center ${
                                  !isConfigured ? 'bg-gray-500/10' : svc.reachable ? 'bg-emerald-500/10' : 'bg-red-500/10'
                                }`}>
                                  <ExchangeIcon exchange={key.replace('exchange_', '')} size={20} />
                                </div>
                                <div>
                                  <span className="text-white text-sm font-medium block">{svc.label}</span>
                                  {isConfigured && svc.latency_ms != null && (
                                    <span className="text-gray-600 text-[10px] tabular-nums">{svc.latency_ms}ms</span>
                                  )}
                                  {!isConfigured && (
                                    <span className="text-gray-600 text-[10px]">{t('settings.notConfigured')}</span>
                                  )}
                                </div>
                              </div>
                              <span className={`text-xs font-medium px-2.5 py-1 rounded-lg ${
                                !isConfigured
                                  ? 'bg-white/5 text-gray-500 border border-white/10'
                                  : svc.reachable
                                    ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                                    : 'bg-red-500/10 text-red-400 border border-red-500/20'
                              }`}>
                                {!isConfigured ? '—' : svc.reachable ? t('settings.online') : t('settings.offline')}
                              </span>
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  )}

                  {notifItems.length > 0 && (
                    <div>
                      <div className="flex items-center gap-2 mb-3">
                        <Activity size={16} className="text-gray-500" />
                        <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wider">
                          {t('settings.notifications')}
                        </h3>
                      </div>
                      <div className="space-y-2">
                        {notifItems.map(([key, svc]) => (
                          <div key={key} className="border border-white/[0.08] bg-white/[0.02] rounded-xl p-4 flex items-center justify-between hover:bg-white/[0.04] transition-colors">
                            <div className="flex items-center gap-3">
                              <div className={`w-9 h-9 rounded-lg flex items-center justify-center ${
                                svc.reachable ? 'bg-emerald-500/10' : 'bg-red-500/10'
                              }`}>
                                <Activity size={16} className={svc.reachable ? 'text-emerald-400' : 'text-red-400'} />
                              </div>
                              <div>
                                <span className="text-white text-sm font-medium block">{svc.label}</span>
                                {svc.latency_ms != null && (
                                  <span className="text-gray-600 text-[10px] tabular-nums">{svc.latency_ms}ms</span>
                                )}
                              </div>
                            </div>
                            <span className={`text-xs font-medium px-2.5 py-1 rounded-lg ${
                              svc.reachable
                                ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                                : 'bg-red-500/10 text-red-400 border border-red-500/20'
                            }`}>
                              {svc.reachable ? t('settings.online') : t('settings.offline')}
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>

                {/* ── Circuit Breakers ── */}
                {cbEntries.length > 0 && (
                  <div>
                    <div className="flex items-center gap-2 mb-3">
                      <Shield size={16} className="text-gray-500" />
                      <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wider">
                        {t('settings.circuitBreakers')}
                      </h3>
                      <span className="text-xs px-2 py-0.5 rounded-full bg-white/5 text-gray-500 border border-white/10 tabular-nums">
                        {cbHealthy}/{cbEntries.length}
                      </span>
                    </div>
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
                      {cbEntries.map(([name, cb]) => (
                        <div key={name} className="border border-white/[0.08] bg-white/[0.02] rounded-xl px-4 py-3 flex items-center justify-between hover:bg-white/[0.04] transition-colors">
                          <div className="flex items-center gap-2.5">
                            <span className={`w-2 h-2 rounded-full flex-shrink-0 ${
                              cb.state === 'closed' ? 'bg-emerald-400' : cb.state === 'open' ? 'bg-red-400 animate-pulse' : 'bg-yellow-400 animate-pulse'
                            }`} />
                            <span className="text-white text-xs font-medium">{cb.name}</span>
                          </div>
                          <span className={`text-[10px] font-medium px-2 py-0.5 rounded-md ${
                            cb.state === 'closed'
                              ? 'bg-emerald-500/10 text-emerald-400'
                              : cb.state === 'open'
                                ? 'bg-red-500/10 text-red-400'
                                : 'bg-yellow-500/10 text-yellow-400'
                          }`}>
                            {circuitLabel(cb.state)}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </>
            )
          })() : (
            <div className="flex flex-col items-center justify-center py-16 space-y-4">
              <div className="w-12 h-12 rounded-xl bg-white/5 flex items-center justify-center">
                <Activity size={22} className="text-gray-600" />
              </div>
              <div className="text-center">
                <p className="text-gray-400 text-sm">{connLoading ? t('settings.refreshing') : t('settings.connectionsDesc')}</p>
                {!connLoading && (
                  <button onClick={loadConnectionStatus}
                    className="mt-3 px-4 py-2 text-sm bg-primary-600 text-white rounded-xl hover:bg-primary-700 transition-colors">
                    {t('settings.refreshStatus')}
                  </button>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Guided Tour */}
      <GuidedTour tourId="settings" steps={settingsTourSteps} />
    </div>
  )
}

/* ─── Settings Tour Steps ─────────────────────────────────────────── */

const settingsTourSteps: TourStep[] = [
  {
    target: '[data-tour="settings-tabs"]',
    titleKey: 'tour.settingsTabsTitle',
    descriptionKey: 'tour.settingsTabsDesc',
    position: 'bottom',
  },
  {
    target: '[data-tour="settings-api-keys"]',
    titleKey: 'tour.settingsApiKeysTitle',
    descriptionKey: 'tour.settingsApiKeysDesc',
    position: 'bottom',
  },
  {
    target: '[data-tour="settings-test-conn"]',
    titleKey: 'tour.settingsTestConnTitle',
    descriptionKey: 'tour.settingsTestConnDesc',
    position: 'bottom',
  },
]
