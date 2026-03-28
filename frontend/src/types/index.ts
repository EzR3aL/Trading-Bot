export interface User {
  id: number
  username: string
  email: string | null
  role: 'admin' | 'user'
  language: 'de' | 'en'
  is_active: boolean
  totp_enabled?: boolean
  auth_provider?: string
  last_login_at?: string | null
  created_at?: string | null
  exchanges?: string[]
  active_bots?: number
  total_trades?: number
}

export interface TokenResponse {
  access_token: string
  refresh_token?: string
  token_type: string
  expires_in: number
}

export interface Trade {
  id: number
  symbol: string
  side: 'long' | 'short'
  size: number
  entry_price: number
  exit_price: number | null
  take_profit: number
  stop_loss: number
  leverage: number
  confidence: number
  reason: string
  status: 'open' | 'closed' | 'cancelled'
  pnl: number | null
  pnl_percent: number | null
  fees: number
  funding_paid: number
  builder_fee: number
  entry_time: string
  exit_time: string | null
  exit_reason: string | null
  exchange: string
  demo_mode: boolean
  bot_name: string | null
  bot_exchange: string | null
  trailing_stop_active?: boolean | null
  trailing_stop_price?: number | null
  trailing_stop_distance?: number | null
  trailing_stop_distance_pct?: number | null
  can_close_at_loss?: boolean | null
}

export interface TradeListResponse {
  trades: Trade[]
  total: number
  page: number
  per_page: number
}

export interface Statistics {
  period_days: number
  total_trades: number
  winning_trades: number
  losing_trades: number
  win_rate: number
  total_pnl: number
  total_fees: number
  total_funding: number
  total_builder_fees: number
  net_pnl: number
  avg_pnl_percent: number
  best_trade: number
  worst_trade: number
}

export interface DailyStats {
  date: string
  trades: number
  pnl: number
  fees: number
  funding: number
  builder_fees: number
  wins: number
  losses: number
}

export interface TradingConfig {
  max_trades_per_day: number
  daily_loss_limit_percent: number
  position_size_percent: number
  leverage: number
  take_profit_percent: number
  stop_loss_percent: number
  trading_pairs: string[]
  demo_mode: boolean
}

export interface StrategyConfig {
  fear_greed_extreme_fear: number
  fear_greed_extreme_greed: number
  long_short_crowded_longs: number
  long_short_crowded_shorts: number
  funding_rate_high: number
  funding_rate_low: number
  high_confidence_min: number
  low_confidence_min: number
}

export interface ExchangeInfo {
  name: string
  display_name: string
  supports_demo: boolean
  auth_type: string
  requires_passphrase: boolean
}

export interface ExchangeConnectionStatus {
  exchange_type: string
  api_keys_configured: boolean
  demo_api_keys_configured: boolean
  affiliate_uid?: string | null
  affiliate_verified?: boolean | null
}

export interface ConfigResponse {
  trading: TradingConfig | null
  strategy: StrategyConfig | null
  connections: ExchangeConnectionStatus[]
  // Deprecated
  exchange_type: string
  api_keys_configured: boolean
  demo_api_keys_configured: boolean
}

export interface ServiceStatus {
  label: string
  type: 'data_source' | 'exchange' | 'notification'
  reachable: boolean
  status_code?: number | null
  latency_ms?: number
  configured?: boolean
  error?: string
}

export interface ConnectionsStatusResponse {
  timestamp: string
  services: Record<string, ServiceStatus>
  circuit_breakers: Record<string, {
    name: string
    state: 'closed' | 'open' | 'half_open'
    stats: {
      total_calls: number
      successful_calls: number
      failed_calls: number
      success_rate: number
      consecutive_failures: number
    }
  }>
}

// Admin UID entry
export interface AdminUidEntry {
  connection_id: number
  username: string
  exchange_type: string
  affiliate_uid: string
  affiliate_verified: boolean
  submitted_at: string | null
  verify_method: 'auto' | 'manual'
}

// Hyperliquid revenue info
export interface HlRevenueInfo {
  builder?: {
    configured: boolean
    user_approved: boolean
    address?: string
    fee_percent?: string
  }
  referral?: {
    configured: boolean
    user_referred: boolean
    code?: string
    link?: string
  }
  earnings?: {
    total_builder_fees_30d: number
    trades_with_builder_fee: number
    monthly_estimate: number
  }
}

// Portfolio types
export interface ExchangeSummary {
  exchange: string
  total_pnl: number
  total_trades: number
  winning_trades: number
  win_rate: number
  total_fees: number
  total_funding: number
}

export interface PortfolioSummary {
  total_pnl: number
  total_trades: number
  overall_win_rate: number
  total_fees: number
  total_funding: number
  exchanges: ExchangeSummary[]
}

export interface PortfolioPosition {
  exchange: string
  symbol: string
  side: string
  size: number
  entry_price: number
  current_price: number
  unrealized_pnl: number
  leverage: number
  margin: number
  bot_name?: string
  demo_mode?: boolean
  trailing_stop_active?: boolean
  trailing_stop_price?: number
  trailing_stop_distance_pct?: number
  can_close_at_loss?: boolean
}

export interface PortfolioDaily {
  date: string
  exchange: string
  pnl: number
  trades: number
  fees: number
}

export interface PortfolioAllocation {
  exchange: string
  balance: number
  currency: string
}
