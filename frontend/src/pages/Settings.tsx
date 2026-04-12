import { lazy, Suspense, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronDown, ExternalLink, Zap } from 'lucide-react'
import api from '../api/client'
import { getApiErrorMessage } from '../utils/api-error'
import { useAuthStore } from '../stores/authStore'
import type { ExchangeConnectionStatus, ExchangeInfo } from '../types'
import { ExchangeIcon } from '../components/ui/ExchangeLogo'
import GuidedTour, { TourHelpButton, type TourStep } from '../components/ui/GuidedTour'
// Lazy-load HyperliquidSetup to keep heavy Web3 deps (rainbowkit, wagmi, viem ~500KB)
// out of the main bundle — only loaded when Hyperliquid exchange is active
const HyperliquidSetup = lazy(() => import('../components/hyperliquid/HyperliquidSetup'))

/* ------------------------------------------------------------------ */
/*  Inline Key Form (used inside accordion)                           */
/* ------------------------------------------------------------------ */

function KeyForm({
  label, configured, keyValue, secretValue, passphraseValue,
  onKeyChange, onSecretChange, onPassphraseChange,
  onSave, onTest, onDelete, saving, t, showPassphrase, authType,
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
  onDelete?: () => void
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
      <div className="flex flex-wrap gap-2">
        <button onClick={onSave} disabled={saving}
          className="px-3 py-1.5 text-sm bg-primary-600 text-white rounded hover:bg-primary-700 disabled:opacity-50">
          {t('settings.save')}
        </button>
        <button onClick={onTest} disabled={!configured}
          className="px-3 py-1.5 text-sm bg-gray-700 text-white rounded hover:bg-gray-600 disabled:opacity-50">
          {t('settings.testConnection')}
        </button>
        {onDelete && configured && (
          <button onClick={onDelete} disabled={saving}
            className="ml-auto px-3 py-1.5 text-sm bg-red-900/40 text-red-300 border border-red-700/40 rounded hover:bg-red-900/60 hover:border-red-600/60 disabled:opacity-50 transition-colors">
            {t('settings.deleteKeys')}
          </button>
        )}
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
  const [exchanges, setExchanges] = useState<ExchangeInfo[]>([])
  const [connections, setConnections] = useState<ExchangeConnectionStatus[]>([])
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')

  // Per-exchange API key forms
  const [keyForms, setKeyForms] = useState<Record<string, ExchangeKeyForm>>({})

  // Accordion state
  const [openExchange, setOpenExchange] = useState<string | null>(null)

  // Hyperliquid referral (user-facing)
  const [hlReferralInfo, setHlReferralInfo] = useState<{ referral_code?: string; referral_required?: boolean; referral_verified?: boolean; needs_referral?: boolean } | null>(null)

  // Affiliate UID (user-facing)
  const [userAffiliateLinks, setUserAffiliateLinks] = useState<Record<string, { affiliate_url: string; label: string | null; uid_required: boolean }>>({})
  const [uidForms, setUidForms] = useState<Record<string, string>>({})

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
      // Reload HL referral info after saving credentials
      if (exchangeType === 'hyperliquid') {
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

  const deleteKeys = async (exchangeType: string, mode: 'live' | 'demo') => {
    const modeLabel = mode === 'demo' ? t('common.demo') : t('common.live')
    if (!window.confirm(t('settings.confirmDeleteKeys', { mode: modeLabel, exchange: exchangeType }))) {
      return
    }
    setSaving(true)
    try {
      await api.delete(`/config/exchange-connections/${exchangeType}/keys?mode=${mode}`)
      const res = await api.get('/config/exchange-connections')
      setConnections(res.data.connections || [])
      // Clear the corresponding form fields if they had values
      if (mode === 'live') {
        updateForm(exchangeType, { apiKey: '', apiSecret: '', passphrase: '' })
      } else {
        updateForm(exchangeType, { demoApiKey: '', demoApiSecret: '', demoPassphrase: '' })
      }
      showMessage(t('settings.keysDeleted', { mode: modeLabel, exchange: exchangeType }))
    } catch (err) {
      showMessage(getApiErrorMessage(err, t('settings.deleteKeysFailed')))
    }
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

  // Load HL referral info when HL accordion opens + auto-show setup if credentials exist
  useEffect(() => {
    if (openExchange === 'hyperliquid') {
      if (!hlReferralInfo) loadHlReferralInfo()
    }
  }, [openExchange])

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

      {/* API Keys */}
      {(() => {
        const liveCount = exchanges.filter(ex => getConn(ex.name)?.api_keys_configured).length
        const demoCount = exchanges.filter(ex => getConn(ex.name)?.demo_api_keys_configured).length
        const totalConfigured = liveCount + demoCount
        const totalPossible = exchanges.length + exchanges.filter(ex => ex.supports_demo).length
        const configPct = totalPossible > 0 ? Math.round((totalConfigured / totalPossible) * 100) : 0
        return (
          <div className="space-y-6" data-tour="settings-api-keys">
            {/* Summary Bar */}
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

            {/* Exchange Cards */}
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
                          onDelete={() => deleteKeys(ex.name, 'live')}
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
                              onDelete={() => deleteKeys(ex.name, 'demo')}
                              saving={saving} t={t} showPassphrase={showPass} authType={ex.auth_type}
                            />
                            {ex.auth_type === 'eth_wallet' && (
                              <div className="p-2.5 bg-amber-900/20 border border-amber-800/40 rounded-lg text-xs text-amber-300">
                                {t('settings.hyperliquidTestnetNote')}
                              </div>
                            )}
                          </>
                        )}

                        {/* Hyperliquid: Inline setup (affiliate + builder fee) — always shown for non-admins */}
                        {ex.name === 'hyperliquid' && !isAdmin && (
                          <Suspense fallback={
                            <div className="flex items-center justify-center py-8">
                              <div className="w-6 h-6 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin" />
                            </div>
                          }>
                            <HyperliquidSetup onComplete={() => loadHlReferralInfo()} />
                          </Suspense>
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

      {/* Guided Tour */}
      <GuidedTour tourId="settings" steps={settingsTourSteps} />
    </div>
  )
}

/* --- Settings Tour Steps --- */

const settingsTourSteps: TourStep[] = [
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
