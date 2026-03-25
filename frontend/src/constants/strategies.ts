// Display names for bot strategy types
export const STRATEGY_DISPLAY: Record<string, string> = {
  llm_signal: 'KI-Companion',
  sentiment_surfer: 'Sentiment Surfer',
  liquidation_hunter: 'Liquidation Hunter',
  degen: 'Degen',
  edge_indicator: 'Edge Indicator',
  contrarian_pulse: 'Contrarian Pulse',
}

// Convert a strategy key to a human-readable label
export function strategyLabel(name: string): string {
  return STRATEGY_DISPLAY[name] || name.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}
