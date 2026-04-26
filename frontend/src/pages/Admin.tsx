import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
import AdminTabs from '../components/admin/AdminTabs'
import TabLoader from '../components/admin/TabLoader'
import AffiliateLinksTab from '../components/admin/AffiliateLinksTab'
import HyperliquidAdminTab from '../components/admin/HyperliquidAdminTab'
import ConnectionsTab from '../components/admin/ConnectionsTab'
import { useAdminApi } from '../components/admin/useAdminApi'
import type { TabKey } from '../components/admin/types'

const AdminUsers = lazy(() => import('./AdminUsers'))
const AdminBroadcasts = lazy(() => import('./AdminBroadcasts'))
const AdminRevenue = lazy(() => import('./AdminRevenue'))

export default function Admin() {
  const { t } = useTranslation()
  useDocumentTitle(t('nav.admin'))
  const [activeTab, setActiveTab] = useState<TabKey>('users')
  const [affiliateCardOpen, setAffiliateCardOpen] = useState<Record<string, boolean>>({})

  // Shared transient banner message + #332 timer cleanup ref.
  const [message, setMessage] = useState('')
  const messageTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const showMessage = (msg: string) => {
    setMessage(msg)
    if (messageTimerRef.current) clearTimeout(messageTimerRef.current)
    messageTimerRef.current = setTimeout(() => {
      setMessage('')
      messageTimerRef.current = null
    }, 3000)
  }

  // Clear any pending showMessage timer on unmount so the deferred setMessage
  // does not fire against a stale component.
  useEffect(() => {
    return () => {
      if (messageTimerRef.current) {
        clearTimeout(messageTimerRef.current)
        messageTimerRef.current = null
      }
    }
  }, [])

  const adminApi = useAdminApi(showMessage)
  const {
    connStatus, connLoading, loadConnectionStatus,
    hlRevenue, hlLoading, loadHlRevenue,
    hlAdminSettings, hlAdminForm, setHlAdminForm, hlAdminSaving,
    loadHlAdminSettings, saveHlAdminSettings,
    saving, affiliateLinks, affiliateForms, setAffiliateForms, affiliateLoaded,
    loadAffiliateLinks, saveAffiliateLink, saveAllAffiliateLinks, deleteAffiliateLink,
    adminUids, adminUidPage, adminUidPages, adminUidTotal,
    adminUidSearch, setAdminUidSearch, adminUidFilter, setAdminUidFilter, adminUidStats,
    loadAdminUids, verifyAdminUid,
  } = adminApi

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
    if (activeTab === 'hyperliquid') {
      loadHlAdminSettings()
      loadHlRevenue()
    }
  }, [activeTab])

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-white">Admin</h1>
      </div>

      {message && (
        <div className="mb-4 p-3 bg-emerald-500/10 dark:bg-primary-900/30 border border-emerald-500/20 dark:border-primary-800 rounded text-emerald-700 dark:text-primary-400 text-sm">
          {message}
        </div>
      )}

      <AdminTabs activeTab={activeTab} onChange={setActiveTab} />

      {activeTab === 'users' && (
        <Suspense fallback={<TabLoader />}>
          <AdminUsers />
        </Suspense>
      )}

      {activeTab === 'broadcasts' && (
        <Suspense fallback={<TabLoader />}>
          <AdminBroadcasts />
        </Suspense>
      )}

      {activeTab === 'revenue' && (
        <Suspense fallback={<TabLoader />}>
          <AdminRevenue />
        </Suspense>
      )}

      {activeTab === 'affiliateLinks' && (
        <AffiliateLinksTab
          affiliateLinks={affiliateLinks}
          affiliateForms={affiliateForms}
          affiliateCardOpen={affiliateCardOpen}
          saving={saving}
          adminUids={adminUids}
          adminUidStats={adminUidStats}
          adminUidPage={adminUidPage}
          adminUidPages={adminUidPages}
          adminUidTotal={adminUidTotal}
          adminUidSearch={adminUidSearch}
          adminUidFilter={adminUidFilter}
          onChangeForm={(ex, next) => setAffiliateForms(prev => ({ ...prev, [ex]: next }))}
          onToggleCard={(ex) => setAffiliateCardOpen(prev => ({ ...prev, [ex]: !prev[ex] }))}
          onSaveOne={saveAffiliateLink}
          onSaveAll={saveAllAffiliateLinks}
          onDelete={deleteAffiliateLink}
          onSearchChange={(next) => {
            setAdminUidSearch(next)
            loadAdminUids(1, next, adminUidFilter)
          }}
          onFilterChange={(next) => {
            setAdminUidFilter(next)
            loadAdminUids(1, adminUidSearch, next)
          }}
          onPageChange={loadAdminUids}
          onVerify={verifyAdminUid}
        />
      )}

      {activeTab === 'hyperliquid' && (
        <HyperliquidAdminTab
          hlRevenue={hlRevenue}
          hlLoading={hlLoading}
          hlAdminSettings={hlAdminSettings}
          hlAdminForm={hlAdminForm}
          hlAdminSaving={hlAdminSaving}
          onRefreshRevenue={loadHlRevenue}
          onChangeAdminForm={setHlAdminForm}
          onSaveAdminSettings={saveHlAdminSettings}
        />
      )}

      {activeTab === 'connections' && (
        <ConnectionsTab
          connStatus={connStatus}
          connLoading={connLoading}
          onRefresh={loadConnectionStatus}
        />
      )}
    </div>
  )
}
