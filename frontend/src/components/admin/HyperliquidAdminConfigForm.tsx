import { useTranslation } from 'react-i18next'
import { Settings2 } from 'lucide-react'
import FilterDropdown from '../ui/FilterDropdown'
import type { HlAdminForm, HlAdminSettings } from './types'

interface Props {
  hlAdminSettings: HlAdminSettings | null
  hlAdminForm: HlAdminForm
  hlAdminSaving: boolean
  onChangeForm: (next: HlAdminForm) => void
  onSave: () => void
}

/**
 * Builder address / fee / referral admin config form for the Hyperliquid tab.
 * Renders the source provenance hint (db / env / not set) under each field.
 */
export default function HyperliquidAdminConfigForm({
  hlAdminSettings,
  hlAdminForm,
  hlAdminSaving,
  onChangeForm,
  onSave,
}: Props) {
  const { t } = useTranslation()

  const sourceLabel = (src: string | undefined) => {
    if (!src) return null
    return t('settings.hlSource', {
      source: src === 'db' ? t('settings.hlSourceDb') : src === 'env' ? t('settings.hlSourceEnv') : t('settings.hlSourceNotSet'),
    })
  }

  return (
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
                onChange={(e) => onChangeForm({ ...hlAdminForm, builder_address: e.target.value })}
                placeholder="0x..."
                className="filter-select w-full text-sm font-mono"
              />
              {hlAdminSettings?.sources?.builder_address && (
                <p className="text-[10px] text-gray-600 mt-1">
                  {sourceLabel(hlAdminSettings.sources.builder_address)}
                </p>
              )}
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1.5">{t('settings.hlBuilderFeeLabel')}</label>
              <FilterDropdown
                value={String(hlAdminForm.builder_fee)}
                onChange={val => onChangeForm({ ...hlAdminForm, builder_fee: parseInt(val) })}
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
                  {sourceLabel(hlAdminSettings.sources.builder_fee)}
                </p>
              )}
            </div>
          </div>
          <div className="sm:w-1/2">
            <label className="block text-xs text-gray-500 mb-1.5">{t('settings.hlReferralCode')}</label>
            <input
              type="text"
              value={hlAdminForm.referral_code}
              onChange={(e) => onChangeForm({ ...hlAdminForm, referral_code: e.target.value })}
              placeholder="e.g. MYCODE"
              className="filter-select w-full text-sm"
            />
            {hlAdminSettings?.sources?.referral_code && (
              <p className="text-[10px] text-gray-600 mt-1">
                {sourceLabel(hlAdminSettings.sources.referral_code)}
              </p>
            )}
          </div>
          <div className="pt-1">
            <button
              onClick={onSave}
              disabled={hlAdminSaving}
              className="px-4 py-2 text-sm bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50 transition-colors"
            >
              {hlAdminSaving ? t('settings.hlSaving') : t('settings.hlSaveSettings')}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
