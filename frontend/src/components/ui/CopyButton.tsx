import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Copy, Check } from 'lucide-react'
import { showSuccess, showError } from '../../utils/toast'

/**
 * Small icon-only button that copies a string to the clipboard and
 * flashes a check icon + toast on success. Centralises the
 * "wallet/address/trade-id copy" affordance so every such surface
 * behaves consistently.
 */
export default function CopyButton({
  value,
  label,
  className = '',
  size = 14,
}: {
  value: string
  /** Shown in `aria-label` and in the success toast, e.g. "Wallet address". */
  label: string
  className?: string
  size?: number
}) {
  const { t } = useTranslation()
  const [copied, setCopied] = useState(false)

  const handleCopy = async (e: React.MouseEvent) => {
    e.stopPropagation()
    try {
      await navigator.clipboard.writeText(value)
      setCopied(true)
      showSuccess(t('common.copiedToast', { label }))
      setTimeout(() => setCopied(false), 1500)
    } catch {
      showError(t('common.copyFailed'))
    }
  }

  return (
    <button
      type="button"
      onClick={handleCopy}
      aria-label={t('common.copyValue', { label })}
      title={t('common.copyValue', { label })}
      className={`inline-flex items-center justify-center p-1 rounded text-gray-400 hover:text-white hover:bg-white/5 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500/60 ${className}`}
    >
      {copied ? <Check size={size} className="text-emerald-400" /> : <Copy size={size} />}
    </button>
  )
}
