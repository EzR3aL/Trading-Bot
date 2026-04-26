// Shared types, colors and number formatters for the BotPerformance page.

export const BOT_COLORS = [
  '#00e676', '#3b82f6', '#f59e0b', '#ff5252', '#a855f7',
  '#06b6d4', '#ec4899', '#84cc16', '#f97316', '#6366f1',
]

export const PNL_POS = '#22c55e'
export const PNL_NEG = '#ef4444'
export const FEES_COLOR = '#f59e0b'
export const FUNDING_COLOR = '#8b5cf6'
export const CUMULATIVE_COLOR = '#3b82f6'

export interface BotCompareData {
  bot_id: number
  name: string
  strategy_type: string
  exchange_type: string
  mode: string
  total_trades: number
  total_pnl: number
  total_fees: number
  total_funding: number
  win_rate: number
  wins: number
  last_direction: string | null
  last_confidence: number | null

  series: { date: string; cumulative_pnl: number }[]
}

export interface BotDetailRecentTrade {
  id: number
  symbol: string
  side: string
  size?: number
  entry_price: number
  exit_price: number | null
  pnl: number
  pnl_percent: number
  confidence: number
  reason: string
  status: string
  fees: number
  funding_paid: number
  leverage?: number
  demo_mode: boolean
  entry_time: string | null
  exit_time: string | null
  exit_reason: string | null
  trailing_stop_active?: boolean | null
  trailing_stop_price?: number | null
  trailing_stop_distance?: number | null
  trailing_stop_distance_pct?: number | null
  can_close_at_loss?: boolean | null
}

export interface BotDetailStats {
  bot_id: number
  bot_name: string
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
  daily_series: { date: string; pnl: number; cumulative_pnl: number; trades: number; wins: number; fees: number; funding: number }[]
  recent_trades: BotDetailRecentTrade[]
}

export interface AffiliateLink {
  exchange_type: string
  affiliate_url: string
  label: string | null
}

export function formatPnl(value: number): string {
  const prefix = value >= 0 ? '+' : ''
  return `${prefix}$${value.toFixed(2)}`
}

export function formatPnlPercent(value: number): string {
  return `${value >= 0 ? '+' : ''}${value.toFixed(1)}%`
}
