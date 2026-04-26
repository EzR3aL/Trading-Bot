import { useTranslation } from 'react-i18next'
import { CheckCircle, Clock, ExternalLink, Users } from 'lucide-react'
import AffiliateLinkCard from './AffiliateLinkCard'
import AdminUidTable from './AdminUidTable'
import {
  AFFILIATE_EXCHANGES,
  type AdminUidFilter,
  type AdminUidStats,
  type AffiliateForm,
  type AffiliateLinkSummary,
} from './types'
import type { AdminUidEntry } from '../../types'

interface Props {
  affiliateLinks: Record<string, AffiliateLinkSummary>
  affiliateForms: Record<string, AffiliateForm>
  affiliateCardOpen: Record<string, boolean>
  saving: boolean
  adminUids: AdminUidEntry[]
  adminUidStats: AdminUidStats
  adminUidPage: number
  adminUidPages: number
  adminUidTotal: number
  adminUidSearch: string
  adminUidFilter: AdminUidFilter
  onChangeForm: (exchange: string, next: AffiliateForm) => void
  onToggleCard: (exchange: string) => void
  onSaveOne: (exchange: string) => void
  onSaveAll: () => void
  onDelete: (exchange: string) => void
  onSearchChange: (next: string) => void
  onFilterChange: (next: AdminUidFilter) => void
  onPageChange: (page: number) => void
  onVerify: (connectionId: number, verified: boolean) => void
}

/**
 * Affiliate Links admin tab. Top summary bar plus a two-column grid:
 * left = AffiliateLinkCard list per supported exchange; right = AdminUidTable
 * for affiliate UID verification.
 */
export default function AffiliateLinksTab({
  affiliateLinks,
  affiliateForms,
  affiliateCardOpen,
  saving,
  adminUids,
  adminUidStats,
  adminUidPage,
  adminUidPages,
  adminUidTotal,
  adminUidSearch,
  adminUidFilter,
  onChangeForm,
  onToggleCard,
  onSaveOne,
  onSaveAll,
  onDelete,
  onSearchChange,
  onFilterChange,
  onPageChange,
  onVerify,
}: Props) {
  const { t } = useTranslation()
  const configuredAff = AFFILIATE_EXCHANGES.filter(ex => !!affiliateLinks[ex]).length
  const hasAnyForm = Object.values(affiliateForms).some(f => f.url)

  return (
    <div className="space-y-6">
      {/* Summary Bar */}
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
              onClick={onSaveAll}
              disabled={saving || !hasAnyForm}
              className="px-3 py-1.5 text-xs bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50 transition-colors flex items-center gap-1.5"
            >
              {t('settings.saveAll')}
            </button>
          </div>
          <div className="space-y-3">
            {AFFILIATE_EXCHANGES.map((ex) => {
              const form = affiliateForms[ex] || { url: '', label: '', active: true, uidRequired: false }
              return (
                <AffiliateLinkCard
                  key={ex}
                  exchange={ex}
                  form={form}
                  linkSummary={affiliateLinks[ex]}
                  open={!!affiliateCardOpen[ex]}
                  saving={saving}
                  onToggleOpen={() => onToggleCard(ex)}
                  onChangeForm={(next) => onChangeForm(ex, next)}
                  onSave={() => onSaveOne(ex)}
                  onDelete={() => onDelete(ex)}
                />
              )
            })}
          </div>
        </div>

        {/* Right: Admin UID Management */}
        <AdminUidTable
          uids={adminUids}
          search={adminUidSearch}
          filter={adminUidFilter}
          stats={adminUidStats}
          page={adminUidPage}
          totalPages={adminUidPages}
          total={adminUidTotal}
          onSearchChange={onSearchChange}
          onFilterChange={onFilterChange}
          onPageChange={onPageChange}
          onVerify={onVerify}
        />
      </div>
    </div>
  )
}
