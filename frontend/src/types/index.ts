export interface User {
  id: number
  username: string
  email: string | null
  role: 'admin' | 'user'
  language: 'de' | 'en'
  is_active: boolean
}

export interface TokenResponse {
  access_token: string
  refresh_token: string
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
  entry_time: string
  exit_time: string | null
  exit_reason: string | null
  exchange: string
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
  net_pnl: number
  avg_pnl_percent: number
  best_trade: number
  worst_trade: number
}

export interface Preset {
  id: number
  name: string
  description: string | null
  exchange_type: string
  is_active: boolean
  trading_config: TradingConfig | null
  strategy_config: StrategyConfig | null
  trading_pairs: string[] | null
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

export interface BotStatus {
  is_running: boolean
  exchange_type: string | null
  demo_mode: boolean
  active_preset_id: number | null
  active_preset_name: string | null
  started_at: string | null
}

export interface ExchangeInfo {
  name: string
  display_name: string
  supports_demo: boolean
  auth_type: string
  requires_passphrase: boolean
}

export interface ConfigResponse {
  trading: TradingConfig | null
  strategy: StrategyConfig | null
  discord: { webhook_url: string | null } | null
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
