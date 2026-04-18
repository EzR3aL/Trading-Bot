import { useTranslation } from 'react-i18next'
import {
  TrendingUp,
  TrendingDown,
  Target,
  ShieldOff,
  LogOut,
  CircleDot,
  Server,
  Cpu,
  Hand,
  AlertOctagon,
  Clock,
  HelpCircle,
} from 'lucide-react'

type ReasonStyle = {
  icon: typeof TrendingUp
  bg: string
  text: string
  border: string
}

const EXIT_REASON_CONFIG: Record<string, ReasonStyle> = {
  // — New precise codes (issue #194) ——————————————————————————————
  TRAILING_STOP_NATIVE: {
    icon: Server,
    bg: 'bg-emerald-500/10',
    text: 'text-emerald-300',
    border: 'border-emerald-500/20',
  },
  TRAILING_STOP_SOFTWARE: {
    icon: Cpu,
    bg: 'bg-blue-500/10',
    text: 'text-blue-300',
    border: 'border-blue-500/20',
  },
  TAKE_PROFIT_NATIVE: {
    icon: Target,
    bg: 'bg-emerald-500/10',
    text: 'text-emerald-400',
    border: 'border-emerald-500/20',
  },
  STOP_LOSS_NATIVE: {
    icon: ShieldOff,
    bg: 'bg-red-500/10',
    text: 'text-red-400',
    border: 'border-red-500/20',
  },
  MANUAL_CLOSE_UI: {
    icon: Hand,
    bg: 'bg-white/5',
    text: 'text-gray-400',
    border: 'border-white/10',
  },
  MANUAL_CLOSE_EXCHANGE: {
    icon: LogOut,
    bg: 'bg-white/5',
    text: 'text-gray-300',
    border: 'border-white/10',
  },
  STRATEGY_EXIT: {
    icon: CircleDot,
    bg: 'bg-amber-500/10',
    text: 'text-amber-400',
    border: 'border-amber-500/20',
  },
  LIQUIDATION: {
    icon: AlertOctagon,
    bg: 'bg-red-500/15',
    text: 'text-red-500',
    border: 'border-red-500/30',
  },
  FUNDING_EXPIRY: {
    icon: Clock,
    bg: 'bg-slate-500/10',
    text: 'text-slate-300',
    border: 'border-slate-500/20',
  },
  EXTERNAL_CLOSE_UNKNOWN: {
    icon: HelpCircle,
    bg: 'bg-white/5',
    text: 'text-gray-400',
    border: 'border-white/10',
  },
  // — Legacy aliases (kept for historical trades) ————————————————
  TRAILING_STOP: {
    icon: TrendingDown,
    bg: 'bg-blue-500/10',
    text: 'text-blue-400',
    border: 'border-blue-500/20',
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

const DEFAULT_CONFIG: ReasonStyle = {
  icon: TrendingUp,
  bg: 'bg-white/5',
  text: 'text-gray-400',
  border: 'border-white/10',
}

// Sort keys by length DESC so longer prefixes (e.g. TRAILING_STOP_NATIVE)
// match before shorter ones (TRAILING_STOP). Computed once at module load.
const PREFIX_KEYS = Object.keys(EXIT_REASON_CONFIG).sort((a, b) => b.length - a.length)

interface ExitReasonBadgeProps {
  reason: string | null
  compact?: boolean
}

export default function ExitReasonBadge({ reason, compact = false }: ExitReasonBadgeProps) {
  const { t } = useTranslation()

  if (!reason) return null

  // Match config by prefix (STRATEGY_EXIT may have extra info like "[BotName] reason").
  // Longest-prefix-first so TRAILING_STOP_NATIVE wins over TRAILING_STOP.
  const key = PREFIX_KEYS.find((k) => reason.startsWith(k)) || ''
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
