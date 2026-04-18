import type {
  RiskLegStatus,
  RiskStateResponse,
  RiskSource,
} from '../types/riskState'

/**
 * Legacy position shape used across MobilePositionCard, Trades, and Portfolio.
 * The current API exposes TP/SL/Trailing as primitive fields; the new
 * risk-state truth endpoint (epic #188) will expose structured legs.
 *
 * This helper bridges both worlds: given a legacy position, synthesize a
 * best-effort RiskStateResponse so RiskStateBadge can render today.
 */
interface LegacyPositionLike {
  trade_id?: number
  symbol?: string
  take_profit?: number | null
  stop_loss?: number | null
  trailing_stop_active?: boolean
  trailing_stop_price?: number | null
  trailing_stop_distance?: number | null
  trailing_stop_distance_pct?: number | null
  trailing_atr_override?: number | null
  native_trailing_stop?: boolean
}

/**
 * Derive a RiskStateResponse from a legacy position object.
 *
 * Assumptions:
 * - TP/SL values that are numeric (not null/0) are treated as `confirmed`.
 * - Source for TP/SL is `unknown` — legacy API doesn't reveal whether a
 *   stop/tp order lives on the exchange. We will switch to `native_exchange`
 *   once the backend from #188 exposes this.
 * - Trailing uses `native_trailing_stop` to pick native vs software source.
 * - No mutation is in flight in legacy mode, so no `pending` or `rejected`.
 *
 * Callers should replace this with the real RiskStateResponse from the API
 * once available.
 */
export function deriveRiskStateFromPosition(
  pos: LegacyPositionLike,
): RiskStateResponse {
  const tp = pos.take_profit != null && pos.take_profit > 0
    ? {
        value: pos.take_profit,
        status: 'confirmed',
        source: 'unknown',
      } as RiskLegStatus
    : null

  const sl = pos.stop_loss != null && pos.stop_loss > 0
    ? {
        value: pos.stop_loss,
        status: 'confirmed',
        source: 'unknown',
      } as RiskLegStatus
    : null

  const trailingSource: RiskSource = pos.native_trailing_stop
    ? 'native_exchange'
    : 'software_bot'

  const trailing = pos.trailing_stop_active
    ? {
        value: pos.trailing_stop_price ?? null,
        distance_atr: pos.trailing_atr_override ?? null,
        distance_pct: pos.trailing_stop_distance_pct ?? null,
        status: 'confirmed',
        source: trailingSource,
      } as RiskLegStatus
    : null

  const overallSource: RiskSource = trailing?.source ?? 'unknown'

  return {
    trade_id: pos.trade_id ?? 0,
    symbol: pos.symbol ?? '',
    tp,
    sl,
    trailing,
    risk_source: overallSource,
  }
}
