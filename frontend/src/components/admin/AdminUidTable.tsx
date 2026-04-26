import { useTranslation } from 'react-i18next'
import { Search, Users } from 'lucide-react'
import Pagination from '../ui/Pagination'
import { ExchangeIcon } from '../ui/ExchangeLogo'
import type { AdminUidEntry } from '../../types'
import type { AdminUidFilter, AdminUidStats } from './types'

interface Props {
  uids: AdminUidEntry[]
  search: string
  filter: AdminUidFilter
  stats: AdminUidStats
  page: number
  totalPages: number
  total: number
  onSearchChange: (next: string) => void
  onFilterChange: (next: AdminUidFilter) => void
  onPageChange: (page: number) => void
  onVerify: (connectionId: number, verified: boolean) => void
}

/**
 * Affiliate UID admin panel: search box, status filter pills, paginated table
 * with verify/reject actions per row. Right-hand column inside the affiliate
 * tab on the admin page.
 */
export default function AdminUidTable({
  uids,
  search,
  filter,
  stats,
  page,
  totalPages,
  total,
  onSearchChange,
  onFilterChange,
  onPageChange,
  onVerify,
}: Props) {
  const { t } = useTranslation()

  return (
    <div className="lg:sticky lg:top-4">
      <div className="flex items-center gap-2 mb-3">
        <Users size={16} className="text-gray-500" />
        <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wider">
          {t('affiliate.affiliateUids')}
        </h3>
        <span className="text-xs px-2 py-0.5 rounded-full bg-white/5 text-gray-500 border border-white/[0.08] tabular-nums">
          {stats.total}
        </span>
        {stats.pending > 0 && (
          <span className="text-[10px] px-2 py-0.5 rounded-full bg-yellow-500/10 text-yellow-400 border border-yellow-500/20 tabular-nums animate-pulse">
            {stats.pending} offen
          </span>
        )}
      </div>
      <div className="border border-white/[0.08] bg-white/[0.02] rounded-xl overflow-hidden">
        <div className="px-4 py-3 border-b border-white/[0.06] bg-white/[0.02]">
          <div className="flex items-center gap-2">
            <div className="relative flex-1">
              <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-500" />
              <input
                type="text"
                value={search}
                onChange={(e) => onSearchChange(e.target.value)}
                placeholder="Username / UID..."
                className="filter-select w-full text-sm !pl-8"
              />
            </div>
            <div className="flex rounded-lg border border-white/[0.08] overflow-hidden shrink-0">
              {(['all', 'pending', 'verified'] as const).map(f => (
                <button key={f} onClick={() => onFilterChange(f)}
                  className={`px-2.5 py-1.5 text-xs transition-colors ${filter === f ? 'bg-white/10 text-white' : 'text-gray-500 hover:text-gray-300'}`}>
                  {f === 'all' ? 'Alle' : f === 'pending' ? 'Offen' : 'Verifiziert'}
                </button>
              ))}
            </div>
          </div>
        </div>

        {uids.length === 0 ? (
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
                {uids.map((item) => {
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
                          <button onClick={() => onVerify(item.connection_id, true)}
                            title={t('affiliate.verifyUid')}
                            className="px-2 py-0.5 text-[10px] bg-emerald-500/10 text-emerald-400 rounded hover:bg-emerald-500/20 transition-colors">
                            {t('affiliate.verifyUid')}
                          </button>
                        )}
                        <button onClick={() => onVerify(item.connection_id, false)}
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

        {totalPages > 1 && (
          <div className="px-4 py-3 border-t border-white/[0.06] flex items-center justify-between">
            <span className="text-[10px] text-gray-600 tabular-nums">{total} Ergebnisse</span>
            <Pagination
              page={page}
              totalPages={totalPages}
              onPageChange={onPageChange}
            />
          </div>
        )}
      </div>
    </div>
  )
}
