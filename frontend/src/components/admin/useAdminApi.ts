import { useCallback, useState } from 'react'
import { useTranslation } from 'react-i18next'
import api from '../../api/client'
import { getApiErrorMessage } from '../../utils/api-error'
import { useToastStore } from '../../stores/toastStore'
import type { AdminUidEntry, ConnectionsStatusResponse, HlRevenueInfo } from '../../types'
import {
  AFFILIATE_EXCHANGES,
  type AdminUidFilter,
  type AdminUidStats,
  type AffiliateForm,
  type AffiliateLinkSummary,
  type HlAdminForm,
  type HlAdminSettings,
} from './types'

interface ShowMessage {
  (msg: string): void
}

/**
 * Custom hook that owns the data-fetching state and HTTP handlers for the
 * Admin page. Extracted from pages/Admin.tsx so the page component stays a
 * thin shell that wires state into the tab sub-components.
 */
export function useAdminApi(showMessage: ShowMessage) {
  const { t } = useTranslation()

  // Connections
  const [connStatus, setConnStatus] = useState<ConnectionsStatusResponse | null>(null)
  const [connLoading, setConnLoading] = useState(false)

  // Saving flag (shared by affiliate save endpoints)
  const [saving, setSaving] = useState(false)

  // Hyperliquid revenue + admin settings
  const [hlRevenue, setHlRevenue] = useState<HlRevenueInfo | null>(null)
  const [hlLoading, setHlLoading] = useState(false)
  const [hlAdminSettings, setHlAdminSettings] = useState<HlAdminSettings | null>(null)
  const [hlAdminForm, setHlAdminForm] = useState<HlAdminForm>({ builder_address: '', builder_fee: 10, referral_code: '' })
  const [hlAdminSaving, setHlAdminSaving] = useState(false)

  // Affiliate links
  const [affiliateLinks, setAffiliateLinks] = useState<Record<string, AffiliateLinkSummary>>({})
  const [affiliateForms, setAffiliateForms] = useState<Record<string, AffiliateForm>>({})
  const [affiliateLoaded, setAffiliateLoaded] = useState(false)

  // Admin UIDs
  const [adminUids, setAdminUids] = useState<AdminUidEntry[]>([])
  const [adminUidPage, setAdminUidPage] = useState(1)
  const [adminUidPages, setAdminUidPages] = useState(1)
  const [adminUidTotal, setAdminUidTotal] = useState(0)
  const [adminUidSearch, setAdminUidSearch] = useState('')
  const [adminUidFilter, setAdminUidFilter] = useState<AdminUidFilter>('all')
  const [adminUidStats, setAdminUidStats] = useState<AdminUidStats>({ total: 0, verified: 0, pending: 0 })

  const loadConnectionStatus = useCallback(async () => {
    setConnLoading(true)
    try {
      const res = await api.get('/config/connections')
      setConnStatus(res.data)
    } catch (err) { showMessage(getApiErrorMessage(err, t('common.loadError', 'Failed to load data'))) }
    setConnLoading(false)
  }, [showMessage, t])

  const loadHlRevenue = useCallback(async () => {
    setHlLoading(true)
    try {
      const res = await api.get('/config/hyperliquid/revenue-summary')
      setHlRevenue(res.data)
    } catch { /* HL not configured - OK */ }
    setHlLoading(false)
  }, [])

  const loadHlAdminSettings = useCallback(async () => {
    try {
      const res = await api.get('/config/hyperliquid/admin-settings')
      setHlAdminSettings(res.data)
      setHlAdminForm({
        builder_address: res.data.builder_address || '',
        builder_fee: res.data.builder_fee || 10,
        referral_code: res.data.referral_code || '',
      })
    } catch { /* not admin or not available */ }
  }, [])

  const saveHlAdminSettings = useCallback(async () => {
    setHlAdminSaving(true)
    try {
      await api.put('/config/hyperliquid/admin-settings', hlAdminForm)
      showMessage(t('settings.hlSettingsSaved'))
      await loadHlAdminSettings()
      loadHlRevenue()
    } catch (err) {
      showMessage(getApiErrorMessage(err, t('settings.hlSettingsFailed')))
    }
    setHlAdminSaving(false)
  }, [hlAdminForm, loadHlAdminSettings, loadHlRevenue, showMessage, t])

  const loadAffiliateLinks = useCallback(async () => {
    try {
      const res = await api.get('/affiliate-links')
      const map: Record<string, AffiliateLinkSummary> = {}
      for (const link of res.data) {
        map[link.exchange_type] = { affiliate_url: link.affiliate_url, label: link.label || '', is_active: link.is_active }
      }
      setAffiliateLinks(map)
      const forms: Record<string, AffiliateForm> = {}
      for (const ex of AFFILIATE_EXCHANGES) {
        const existing = map[ex]
        const existingRaw = res.data.find((l: any) => l.exchange_type === ex)
        forms[ex] = { url: existing?.affiliate_url || '', label: existing?.label || '', active: existing?.is_active ?? true, uidRequired: existingRaw?.uid_required || false }
      }
      setAffiliateForms(forms)
      setAffiliateLoaded(true)
    } catch (err) { console.error('Failed to load affiliate links:', err); useToastStore.getState().addToast('error', t('common.loadError', 'Failed to load data')) }
  }, [t])

  const saveAffiliateLink = useCallback(async (exchange: string) => {
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
  }, [affiliateForms, loadAffiliateLinks, showMessage, t])

  const saveAllAffiliateLinks = useCallback(async () => {
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
  }, [affiliateForms, loadAffiliateLinks, showMessage, t])

  const deleteAffiliateLink = useCallback(async (exchange: string) => {
    setSaving(true)
    try {
      await api.delete(`/affiliate-links/${exchange}`)
      showMessage(t('settings.saved'))
      loadAffiliateLinks()
    } catch (err) { showMessage(getApiErrorMessage(err, t('common.saveFailed'))) }
    setSaving(false)
  }, [loadAffiliateLinks, showMessage, t])

  const loadAdminUids = useCallback(async (page = adminUidPage, search = adminUidSearch, status = adminUidFilter) => {
    try {
      const res = await api.get('/config/admin/affiliate-uids', { params: { page, per_page: 15, search, status } })
      setAdminUids(res.data.items)
      setAdminUidTotal(res.data.total)
      setAdminUidPages(res.data.pages)
      setAdminUidPage(res.data.page)
      setAdminUidStats(res.data.stats)
    } catch {}
  }, [adminUidPage, adminUidSearch, adminUidFilter])

  const verifyAdminUid = useCallback(async (connectionId: number, verified: boolean) => {
    try {
      await api.put(`/config/admin/affiliate-uids/${connectionId}/verify`, { verified })
      await loadAdminUids(adminUidPage, adminUidSearch, adminUidFilter)
      showMessage(verified ? t('affiliate.uidVerified') : t('affiliate.uidRejected'))
    } catch (err) {
      showMessage(getApiErrorMessage(err, t('common.error')))
    }
  }, [adminUidPage, adminUidSearch, adminUidFilter, loadAdminUids, showMessage, t])

  return {
    // connections
    connStatus, connLoading, loadConnectionStatus,
    // hyperliquid
    hlRevenue, hlLoading, loadHlRevenue,
    hlAdminSettings, hlAdminForm, setHlAdminForm, hlAdminSaving,
    loadHlAdminSettings, saveHlAdminSettings,
    // affiliate
    saving, affiliateLinks, affiliateForms, setAffiliateForms, affiliateLoaded,
    loadAffiliateLinks, saveAffiliateLink, saveAllAffiliateLinks, deleteAffiliateLink,
    // admin uids
    adminUids, adminUidPage, adminUidPages, adminUidTotal,
    adminUidSearch, setAdminUidSearch, adminUidFilter, setAdminUidFilter, adminUidStats,
    loadAdminUids, verifyAdminUid,
  }
}
