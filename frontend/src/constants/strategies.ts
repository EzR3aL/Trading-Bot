// Display names for bot strategy types
export const STRATEGY_DISPLAY: Record<string, string> = {
  liquidation_hunter: 'Liquidation Hunter',
  edge_indicator: 'Edge Indicator',
  copy_trading: 'Copy Trading',
}

// Convert a strategy key to a human-readable label
export function strategyLabel(name: string): string {
  return STRATEGY_DISPLAY[name] || name.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}
