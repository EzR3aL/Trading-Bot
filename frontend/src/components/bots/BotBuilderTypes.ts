// Shared type definitions for BotBuilder wizard components

export interface Strategy {
  name: string
  description: string
  param_schema: Record<string, ParamDef>
}

export interface ParamOption {
  value: string
  label: string
}

export interface ParamDef {
  type: string
  label: string
  description: string
  default: number | string | boolean
  min?: number
  max?: number
  options?: (string | ParamOption)[]
  depends_on?: string
  options_map?: Record<string, ParamOption[]>
}

export interface DataSource {
  id: string
  name: string
  description: string
  category: string
  provider: string
  free: boolean
  default: boolean
}

export interface BalancePreview {
  exchange_type: string
  mode: string
  currency: string
  exchange_balance: number
  exchange_equity: number
  existing_allocated_pct: number
  existing_allocated_amount: number
  remaining_balance: number
  has_connection: boolean
  error: string | null
}

export interface SymbolConflict {
  symbol: string
  existing_bot_id: number
  existing_bot_name: string
  existing_bot_mode: string
}

export interface PerAssetEntry {
  position_usdt?: number
  leverage?: number
  tp?: number
  sl?: number
  max_trades?: number
  loss_limit?: number
}

// Strategies that use market data and should show the data sources step
export const DATA_STRATEGIES = ['liquidation_hunter', 'edge_indicator']

// Fixed data sources per strategy (used after selection to show which sources are used)
export const FIXED_STRATEGY_SOURCES: Record<string, string[]> = {
  liquidation_hunter: [
    'fear_greed', 'long_short_ratio', 'funding_rate', 'open_interest', 'spot_price',
  ],
  edge_indicator: [
    'spot_price', 'vwap', 'supertrend', 'spot_volume', 'volatility',
  ],
}

// Backtest-based timeframe recommendations (90-day BTCUSDT backtest)
export const STRATEGY_RECOMMENDATIONS: Record<string, { bestTimeframe: string; scheduleMinutes: number }> = {
  edge_indicator: { bestTimeframe: '4h', scheduleMinutes: 240 },
}

export const CATEGORY_ORDER = ['sentiment', 'futures', 'options', 'spot', 'technical', 'tradfi']

export const EXCHANGES = ['bitget', 'weex', 'hyperliquid', 'bitunix', 'bingx']
export const POPULAR_BASES = ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE', 'AVAX']
