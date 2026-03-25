import { useEffect, useRef } from 'react'
import { AlertTriangle, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'

interface ConfirmModalProps {
  open: boolean
  title: string
  message: string
  confirmLabel?: string
  cancelLabel?: string
  variant?: 'danger' | 'warning' | 'info'
  onConfirm: () => void
  onCancel: () => void
  loading?: boolean
}

export default function ConfirmModal({
  open, title, message, confirmLabel, cancelLabel,
  variant = 'danger', onConfirm, onCancel, loading = false,
}: ConfirmModalProps) {
  const { t } = useTranslation()
  const cancelRef = useRef<HTMLButtonElement>(null)

  // Focus trap + ESC handler
  useEffect(() => {
    if (!open) return
    cancelRef.current?.focus()
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onCancel()
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [open, onCancel])

  if (!open) return null

  const variantStyles = {
    danger: 'bg-red-600 hover:bg-red-700',
    warning: 'bg-yellow-600 hover:bg-yellow-700',
    info: 'bg-blue-600 hover:bg-blue-700',
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="confirm-title"
    >
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onCancel} />
      <div className="relative glass-card p-6 max-w-md w-full rounded-xl shadow-2xl">
        <button
          onClick={onCancel}
          className="absolute top-3 right-3 text-gray-400 hover:text-white p-1"
          aria-label={t('common.close', 'Close')}
        >
          <X size={18} />
        </button>
        <div className="flex items-start gap-4 mb-4">
          <div className={`p-2 rounded-lg ${variant === 'danger' ? 'bg-red-500/20 text-red-400' : variant === 'warning' ? 'bg-yellow-500/20 text-yellow-400' : 'bg-blue-500/20 text-blue-400'}`}>
            <AlertTriangle size={24} />
          </div>
          <div>
            <h3 id="confirm-title" className="text-lg font-semibold text-white">{title}</h3>
            <p className="text-gray-300 mt-1 text-sm">{message}</p>
          </div>
        </div>
        <div className="flex justify-end gap-3 mt-6">
          <button
            ref={cancelRef}
            onClick={onCancel}
            disabled={loading}
            className="px-4 py-2 text-sm rounded-lg bg-gray-700 hover:bg-gray-600 text-white transition-colors focus:outline-none focus:ring-2 focus:ring-gray-500"
          >
            {cancelLabel || t('common.cancel', 'Cancel')}
          </button>
          <button
            onClick={onConfirm}
            disabled={loading}
            className={`px-4 py-2 text-sm rounded-lg text-white transition-colors flex items-center gap-2 focus:outline-none focus:ring-2 focus:ring-offset-2 ${variantStyles[variant]} ${loading ? 'opacity-60 cursor-not-allowed' : ''}`}
          >
            {loading && <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />}
            {confirmLabel || t('common.confirm', 'Confirm')}
          </button>
        </div>
      </div>
    </div>
  )
}
