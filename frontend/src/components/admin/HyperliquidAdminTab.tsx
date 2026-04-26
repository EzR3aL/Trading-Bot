import { useTranslation } from 'react-i18next'
import { DollarSign } from 'lucide-react'
import HyperliquidStatusOverview from './HyperliquidStatusOverview'
import HyperliquidAdminConfigForm from './HyperliquidAdminConfigForm'
import type { HlRevenueInfo } from '../../types'
import type { HlAdminForm, HlAdminSettings } from './types'

interface Props {
  hlRevenue: HlRevenueInfo | null
  hlLoading: boolean
  hlAdminSettings: HlAdminSettings | null
  hlAdminForm: HlAdminForm
  hlAdminSaving: boolean
  onRefreshRevenue: () => void
  onChangeAdminForm: (next: HlAdminForm) => void
  onSaveAdminSettings: () => void
}

/**
 * Hyperliquid admin tab: status overview, earnings tiles, builder/referral
 * config form. Composed from HyperliquidStatusOverview + HyperliquidAdminConfigForm.
 */
export default function HyperliquidAdminTab({
  hlRevenue,
  hlLoading,
  hlAdminSettings,
  hlAdminForm,
  hlAdminSaving,
  onRefreshRevenue,
  onChangeAdminForm,
  onSaveAdminSettings,
}: Props) {
  const { t } = useTranslation()

  return (
    <div className="space-y-6">
      <HyperliquidStatusOverview
        hlRevenue={hlRevenue}
        hlLoading={hlLoading}
        onRefresh={onRefreshRevenue}
      />

      {/* Earnings */}
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

      <HyperliquidAdminConfigForm
        hlAdminSettings={hlAdminSettings}
        hlAdminForm={hlAdminForm}
        hlAdminSaving={hlAdminSaving}
        onChangeForm={onChangeAdminForm}
        onSave={onSaveAdminSettings}
      />
    </div>
  )
}
