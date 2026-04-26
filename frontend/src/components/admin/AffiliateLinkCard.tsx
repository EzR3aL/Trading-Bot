import { useTranslation } from 'react-i18next'
import { ChevronDown } from 'lucide-react'
import { ExchangeIcon } from '../ui/ExchangeLogo'
import type { AffiliateForm, AffiliateLinkSummary } from './types'

interface Props {
  exchange: string
  form: AffiliateForm
  linkSummary: AffiliateLinkSummary | undefined
  open: boolean
  saving: boolean
  onToggleOpen: () => void
  onChangeForm: (next: AffiliateForm) => void
  onSave: () => void
  onDelete: () => void
}

/**
 * Collapsible card that edits the affiliate URL/label/active flag for a single
 * exchange. Header row shows configured/not-configured status; expanded body
 * shows the input fields plus save/delete buttons. Hyperliquid hides the
 * uidRequired toggle (parity with original behavior).
 */
export default function AffiliateLinkCard({
  exchange,
  form,
  linkSummary,
  open,
  saving,
  onToggleOpen,
  onChangeForm,
  onSave,
  onDelete,
}: Props) {
  const { t } = useTranslation()
  const hasExisting = !!linkSummary

  return (
    <div className="border border-white/[0.08] bg-white/[0.02] rounded-xl overflow-hidden">
      <button
        type="button"
        aria-expanded={open}
        className={`w-full text-left appearance-none bg-transparent border-0 px-4 py-2.5 flex items-center justify-between cursor-pointer select-none ${
          open
            ? `border-b ${hasExisting ? 'border-emerald-500/10 bg-emerald-500/[0.03]' : 'border-white/[0.06] bg-white/[0.02]'}`
            : hasExisting ? 'bg-emerald-500/[0.03]' : 'bg-white/[0.02]'
        }`}
        onClick={onToggleOpen}
      >
        <div className="flex items-center gap-2.5">
          <ExchangeIcon exchange={exchange} size={18} />
          <span className="text-xs font-semibold text-gray-300 uppercase tracking-wider capitalize">{exchange}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${
            hasExisting ? 'bg-emerald-500/10 text-emerald-400' : 'bg-white/5 text-gray-500'
          }`}>
            {hasExisting ? t('settings.configured') : t('settings.notConfigured')}
          </span>
          <ChevronDown size={14} className={`text-gray-400 transition-transform duration-200 ${open ? 'rotate-180' : ''}`} />
        </div>
      </button>
      {open && (
        <div className="p-4 space-y-3">
          <div>
            <label className="block text-xs text-gray-500 mb-1">{t('settings.affiliateUrl')}</label>
            <input
              type="text"
              value={form.url}
              onChange={(e) => onChangeForm({ ...form, url: e.target.value })}
              placeholder="https://..."
              className="filter-select w-full text-sm"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">{t('settings.affiliateLabel')}</label>
            <input
              type="text"
              value={form.label}
              onChange={(e) => onChangeForm({ ...form, label: e.target.value })}
              placeholder={t('settings.affiliateLabelPlaceholder')}
              className="filter-select w-full text-sm"
            />
          </div>
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              <input
                type="checkbox"
                id={`aff-active-${exchange}`}
                checked={form.active}
                onChange={(e) => onChangeForm({ ...form, active: e.target.checked })}
                className="rounded border-white/10 bg-white/5 text-primary-600"
              />
              <label htmlFor={`aff-active-${exchange}`} className="text-xs text-gray-400">{t('settings.affiliateActive')}</label>
            </div>
            {exchange !== 'hyperliquid' && (
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  id={`aff-uid-${exchange}`}
                  checked={form.uidRequired}
                  onChange={(e) => onChangeForm({ ...form, uidRequired: e.target.checked })}
                  className="rounded border-white/10 bg-white/5 text-primary-600"
                />
                <label htmlFor={`aff-uid-${exchange}`} className="text-xs text-gray-400">{t('affiliate.uidRequiredToggle')}</label>
              </div>
            )}
          </div>
          <div className="flex gap-2 pt-1">
            <button
              onClick={onSave}
              disabled={saving || !form.url}
              className="px-3 py-1.5 text-xs bg-primary-600 text-white rounded-lg hover:bg-primary-700 disabled:opacity-50 transition-colors"
            >
              {t('settings.save')}
            </button>
            {hasExisting && (
              <button
                onClick={onDelete}
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
}
