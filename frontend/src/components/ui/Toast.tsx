import { useEffect, useState } from 'react'
import { X, CheckCircle, AlertCircle, AlertTriangle, Info } from 'lucide-react'
import { useToastStore, type Toast as ToastType } from '../../stores/toastStore'

const ICONS = {
  success: CheckCircle,
  error: AlertCircle,
  warning: AlertTriangle,
  info: Info,
}

const STYLES = {
  success: 'from-emerald-500/20 to-emerald-500/5 border-emerald-500/30 text-emerald-300',
  error: 'from-red-500/20 to-red-500/5 border-red-500/30 text-red-300',
  warning: 'from-amber-500/20 to-amber-500/5 border-amber-500/30 text-amber-300',
  info: 'from-blue-500/20 to-blue-500/5 border-blue-500/30 text-blue-300',
}

const ICON_STYLES = {
  success: 'text-emerald-400',
  error: 'text-red-400',
  warning: 'text-amber-400',
  info: 'text-blue-400',
}

function ToastItem({ toast }: { toast: ToastType }) {
  const { removeToast } = useToastStore()
  const [isVisible, setIsVisible] = useState(false)
  const [isExiting, setIsExiting] = useState(false)

  const Icon = ICONS[toast.type]

  useEffect(() => {
    // Trigger enter animation
    const enterTimer = setTimeout(() => setIsVisible(true), 10)
    return () => clearTimeout(enterTimer)
  }, [])

  const handleDismiss = () => {
    setIsExiting(true)
    setTimeout(() => removeToast(toast.id), 300)
  }

  // Auto-dismiss with exit animation
  useEffect(() => {
    if (toast.duration && toast.duration > 0) {
      const exitTimer = setTimeout(() => {
        setIsExiting(true)
      }, toast.duration - 300)
      return () => clearTimeout(exitTimer)
    }
  }, [toast.duration])

  return (
    <div
      className={`
        flex items-center gap-3 px-4 py-3 rounded-xl border backdrop-blur-xl
        bg-gradient-to-r ${STYLES[toast.type]}
        shadow-lg shadow-black/20
        transition-all duration-300 ease-out
        ${isVisible && !isExiting ? 'translate-x-0 opacity-100' : 'translate-x-full opacity-0'}
      `}
      role="alert"
      aria-live="polite"
    >
      <Icon size={18} className={`${ICON_STYLES[toast.type]} shrink-0 mt-0.5`} />
      <div className="text-sm font-medium flex-1 space-y-1">
        {toast.message.split('\n').map((line, li) => (
          <p key={li}>
            {line.split(/(https?:\/\/\S+)/g).map((part, i) =>
              /^https?:\/\//.test(part) ? (
                <a key={i} href={part} target="_blank" rel="noopener noreferrer"
                   className="underline hover:opacity-80 break-all font-semibold">
                  {part}
                </a>
              ) : part
            )}
          </p>
        ))}
      </div>
      <button
        onClick={handleDismiss}
        className="p-1 rounded-lg hover:bg-white/10 transition-colors"
        aria-label="Dismiss notification"
      >
        <X size={14} className="opacity-60" />
      </button>
    </div>
  )
}

export default function ToastContainer() {
  const { toasts } = useToastStore()

  return (
    <div className="fixed top-4 right-4 z-50 flex flex-col gap-2 max-w-sm w-full pointer-events-none max-h-[calc(100vh-2rem)] overflow-y-auto overflow-x-hidden" aria-live="polite" role="status">
      {toasts.map((toast) => (
        <div key={toast.id} className="pointer-events-auto">
          <ToastItem toast={toast} />
        </div>
      ))}
    </div>
  )
}
