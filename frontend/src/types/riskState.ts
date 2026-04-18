/**
 * TypeScript types for Risk State representation (TP/SL/Trailing).
 *
 * These types mirror the backend response from the risk-state endpoint
 * introduced in epic #188 (risk-state truth). Each "leg" (TP, SL, Trailing)
 * carries its own confirmation status + source + metadata.
 *
 * NOTE: If Issue #195 (parallel agent) defines these in src/types/index.ts,
 * the merge should consolidate them there. This standalone file ensures
 * RiskStateBadge (#196) is self-contained until merge.
 */

/** Lifecycle status of a single risk leg (TP / SL / Trailing). */
export type RiskLegStatusCode =
  | 'pending' // mutation in-flight, not yet acknowledged by exchange
  | 'confirmed' // active on exchange (native) or in bot (software)
  | 'rejected' // exchange or bot refused the mutation (see `error`)
  | 'cleared' // explicitly removed; no longer active
  | 'cancel_failed' // cancel attempt failed — old value may still be active

/** Where the risk control is enforced. */
export type RiskSource =
  | 'native_exchange' // order placed on exchange (stop/tp order ids)
  | 'software_bot' // monitored by our bot worker, no exchange-side order
  | 'manual_user' // user set this value manually
  | 'unknown' // unclassified / legacy data

/** A single risk leg (take-profit, stop-loss, or trailing-stop). */
export interface RiskLegStatus {
  /** Numeric price level (TP/SL) or trail trigger price. Null for idle legs. */
  value: number | null
  /** Trailing-only: ATR multiplier distance (e.g. 1.4 for 1.4× ATR). */
  distance_atr?: number | null
  /** Trailing-only: percentage distance from current price. */
  distance_pct?: number | null
  /** Current lifecycle state. */
  status: RiskLegStatusCode
  /** Where the leg is enforced (exchange vs bot). */
  source: RiskSource
  /** Exchange order id (only set when source === 'native_exchange'). */
  order_id?: string | null
  /** Round-trip latency for the last mutation (ms). */
  latency_ms?: number | null
  /** Human-readable error when status === 'rejected' or 'cancel_failed'. */
  error?: string | null
}

/** Full risk state for an open position. */
export interface RiskStateResponse {
  trade_id: number
  symbol: string
  tp: RiskLegStatus | null
  sl: RiskLegStatus | null
  trailing: RiskLegStatus | null
  /** Overall aggregate source (worst-case wins: any rejected → rejected). */
  risk_source: RiskSource
  /** Server timestamp of this snapshot (ISO-8601). */
  as_of?: string
}
