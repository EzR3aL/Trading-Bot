// Shared types and helpers for the Bots page family.

export interface BotStatus {
  bot_config_id: number
  name: string
  strategy_type: string
  exchange_type: string
  mode: string
  trading_pairs: string[]
  status: string
  error_message: string | null
  started_at: string | null
  last_analysis: string | null
  trades_today: number
  is_enabled: boolean
  total_trades: number
  total_pnl: number
  total_fees: number
  total_funding: number
  open_trades: number
  schedule_type?: string | null
  schedule_config?: { interval_minutes?: number; hours?: number[] } | null
  risk_profile?: string | null
  copy_source_wallet?: string | null
  copy_max_slots?: number | null
  copy_budget_usdt?: number | null
  builder_fee_approved?: boolean | null
  referral_verified?: boolean | null
}

export interface BotTrade {
  id: number
  symbol: string
  side: string
  size: number
  entry_price: number
  exit_price: number | null
  pnl: number
  pnl_percent: number
  confidence: number
  reason: string
  leverage?: number
  status: string
  demo_mode: boolean
  exchange?: string
  entry_time: string
  exit_time: string | null
  exit_reason: string | null
  fees: number
  funding_paid: number
  trailing_stop_active?: boolean | null
  trailing_stop_price?: number | null
  trailing_stop_distance?: number | null
  trailing_stop_distance_pct?: number | null
  can_close_at_loss?: boolean | null
}

export interface BotStatistics {
  bot_id: number
  bot_name: string
  strategy_type: string
  exchange_type: string
  summary: {
    total_trades: number
    wins: number
    losses: number
    win_rate: number
    total_pnl: number
    total_fees: number
    total_funding: number
    avg_pnl: number
    best_trade: number
    worst_trade: number
  }
  recent_trades: BotTrade[]
}

export interface AffiliateLink {
  exchange_type: string
  affiliate_url: string
  label: string | null
}

export const STATUS_STYLES: Record<string, { text: string; card: string; dot: string }> = {
  running: {
    text: 'text-emerald-400',
    card: 'border-emerald-500/20 hover:border-emerald-500/30',
    dot: 'bg-emerald-500',
  },
  stopped: {
    text: 'text-gray-400',
    card: 'border-white/5 hover:border-white/10',
    dot: 'bg-gray-500',
  },
  idle: {
    text: 'text-gray-500',
    card: 'border-white/5 hover:border-white/10',
    dot: 'bg-gray-600',
  },
  error: {
    text: 'text-red-400',
    card: 'border-red-500/20 hover:border-red-500/30',
    dot: 'bg-red-500',
  },
  starting: {
    text: 'text-amber-400',
    card: 'border-amber-500/20 hover:border-amber-500/30',
    dot: 'bg-amber-500',
  },
}

export const shortenWallet = (w?: string | null): string =>
  w ? `${w.slice(0, 6)}…${w.slice(-4)}` : '—'

export function formatPnl(value: number): string {
  const prefix = value >= 0 ? '+' : ''
  return `${prefix}$${value.toFixed(2)}`
}

export function formatPnlPercent(value: number): string {
  const prefix = value >= 0 ? '+' : ''
  return `${prefix}${value.toFixed(2)}%`
}

export function getScheduleHoursUtc(
  scheduleType?: string | null,
  scheduleConfig?: { interval_minutes?: number; hours?: number[] } | null,
): number[] | null {
  if (scheduleType === 'custom_cron' && scheduleConfig?.hours) {
    return [...scheduleConfig.hours].sort((a, b) => a - b)
  }
  return null
}

import { utcHourToLocal } from '../../utils/timezone'

export function formatHourLocal(utcHour: number): string {
  return String(utcHourToLocal(utcHour)).padStart(2, '0')
}
