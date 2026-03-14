import { useTranslation } from 'react-i18next'
import { TrendingUp, TrendingDown, Target, ShieldOff, LogOut, CircleDot } from 'lucide-react'

const EXIT_REASON_CONFIG: Record<string, {
  icon: typeof TrendingUp
  bg: string
  text: string
  border: string
}> = {
  TRAILING_STOP: {
    icon: TrendingDown,
    bg: 'bg-blue-500/10',
    text: 'text-blue-400',
    border: 'border-blue-500/20',
  },
  STRATEGY_EXIT: {
    icon: CircleDot,
    bg: 'bg-amber-500/10',
    text: 'text-amber-400',
    border: 'border-amber-500/20',
  },
  TAKE_PROFIT: {
    icon: Target,
    bg: 'bg-emerald-500/10',
    text: 'text-emerald-400',
    border: 'border-emerald-500/20',
  },
  STOP_LOSS: {
    icon: ShieldOff,
    bg: 'bg-red-500/10',
    text: 'text-red-400',
    border: 'border-red-500/20',
  },
  EXTERNAL_CLOSE: {
    icon: LogOut,
    bg: 'bg-white/5',
    text: 'text-gray-400',
    border: 'border-white/10',
  },
  MANUAL_CLOSE: {
    icon: LogOut,
    bg: 'bg-white/5',
    text: 'text-gray-400',
    border: 'border-white/10',
  },
}

const DEFAULT_CONFIG = {
  icon: TrendingUp,
  bg: 'bg-white/5',
  text: 'text-gray-400',
  border: 'border-white/10',
}

interface ExitReasonBadgeProps {
  reason: string | null
  compact?: boolean
}

export default function ExitReasonBadge({ reason, compact = false }: ExitReasonBadgeProps) {
  const { t } = useTranslation()

  if (!reason) return null

  // Match config by prefix (STRATEGY_EXIT may have extra info like "[BotName] reason")
  const key = Object.keys(EXIT_REASON_CONFIG).find(k => reason.startsWith(k)) || ''
  const config = EXIT_REASON_CONFIG[key] || DEFAULT_CONFIG
  const Icon = config.icon

  const label = key
    ? t(`trades.exitReasons.${key}`)
    : t('trades.exitReasons.unknown')

  if (compact) {
    return (
      <span className={`inline-flex items-center gap-1 ${config.text}`}>
        <Icon size={13} />
        <span className="text-xs">{label}</span>
      </span>
    )
  }

  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium border ${config.bg} ${config.text} ${config.border}`}>
      <Icon size={13} />
      {label}
    </span>
  )
}
