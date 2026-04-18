import { useTranslation } from 'react-i18next'
import {
  Target,
  ShieldOff,
  Server,
  Cpu,
  Loader2,
  XCircle,
  AlertTriangle,
  Hand,
  HelpCircle,
  TrendingUp,
} from 'lucide-react'
import type {
  RiskLegStatus,
  RiskLegStatusCode,
  RiskSource,
} from '../../types/riskState'

/**
 * RiskStateBadge — compact visualisation of TP/SL/Trailing state per position.
 *
 * Shows one chip per active leg with:
 * - leg icon (Target/ShieldOff/TrendingUp) in leg-specific colour
 * - numeric value (formatted) or trailing distance (ATR × / %)
 * - status indicator: spinner (pending), X (rejected), warning (cancel_failed)
 * - source indicator: Server (exchange) / Cpu (bot) / Hand (manual) / HelpCircle
 *
 * Idle/cleared legs are not rendered. Rejected and cancel_failed legs
 * surface tooltips with the `error` string for recovery guidance.
 */

/** Layout direction — horizontal (desktop) or vertical (compact / mobile). */
interface RiskStateBadgeProps {
  tp: RiskLegStatus | null
  sl: RiskLegStatus | null
  trailing: RiskLegStatus | null
  riskSource: RiskSource
  /** Compact stacks chips vertically for mobile/narrow containers. */
  compact?: boolean
}

/** Which leg a chip represents. Drives icon + color palette. */
type LegKind = 'tp' | 'sl' | 'trailing'

/** Palette + icon per leg kind. Centralised so new legs extend trivially. */
const LEG_CONFIG: Record<LegKind, {
  icon: typeof Target
  color: string
  bgConfirmed: string
  borderConfirmed: string
  labelKey: string
}> = {
  tp: {
    icon: Target,
    color: 'text-emerald-400',
    bgConfirmed: 'bg-emerald-500/10',
    borderConfirmed: 'border-emerald-500/20',
    labelKey: 'trades.riskBadges.tp',
  },
  sl: {
    icon: ShieldOff,
    color: 'text-red-400',
    bgConfirmed: 'bg-red-500/10',
    borderConfirmed: 'border-red-500/20',
    labelKey: 'trades.riskBadges.sl',
  },
  trailing: {
    icon: TrendingUp,
    color: 'text-blue-400',
    bgConfirmed: 'bg-blue-500/10',
    borderConfirmed: 'border-blue-500/20',
    labelKey: 'trades.riskBadges.trail',
  },
}

/** Icon per source. Placed as trailing glyph in each chip. */
const SOURCE_ICON: Record<RiskSource, typeof Server> = {
  native_exchange: Server,
  software_bot: Cpu,
  manual_user: Hand,
  unknown: HelpCircle,
}

/** Format numeric price with thousands separator, max 2 decimals.
 *  Uses en-US locale to ensure consistent formatting across users (crypto
 *  convention), matching the rest of the trading UI (PnL, entry price, etc.). */
function formatPrice(value: number): string {
  return `$${value.toLocaleString('en-US', {
    maximumFractionDigits: 2,
  })}`
}

/** Format trailing distance as "1.4× ATR" or "2.5%". Falls back to empty. */
function formatTrailDistance(leg: RiskLegStatus): string {
  if (leg.distance_atr != null) {
    return `${leg.distance_atr}× ATR`
  }
  if (leg.distance_pct != null) {
    return `${leg.distance_pct.toFixed(2)}%`
  }
  return ''
}

/** Compose tooltip text from leg metadata. Returns null if no data. */
function buildTooltip(leg: RiskLegStatus, t: (key: string) => string): string {
  const parts: string[] = []
  const statusLabel = t(`trades.riskBadges.status.${leg.status}`)
  parts.push(statusLabel)
  if (leg.order_id) {
    parts.push(`Order: ${leg.order_id}`)
  }
  if (leg.latency_ms != null) {
    parts.push(`Latency: ${leg.latency_ms}ms`)
  }
  if (leg.error) {
    parts.push(`${leg.error}`)
  }
  return parts.join(' · ')
}

/** Single chip for one leg. Handles status-specific styling + tooltip. */
function RiskChip({
  leg,
  kind,
}: {
  leg: RiskLegStatus
  kind: LegKind
}) {
  const { t } = useTranslation()
  const config = LEG_CONFIG[kind]
  const LegIcon = config.icon
  const SourceIcon = SOURCE_ICON[leg.source] ?? HelpCircle

  // Content: value or trailing-distance
  const legLabel = t(config.labelKey)
  const valueText =
    kind === 'trailing'
      ? [formatTrailDistance(leg), leg.value != null ? `@ ${formatPrice(leg.value)}` : '']
          .filter(Boolean)
          .join(' ')
      : leg.value != null
        ? formatPrice(leg.value)
        : ''

  const tooltip = buildTooltip(leg, t)
  const sourceLabel = t(`trades.riskBadges.source.${leg.source}`)
  const ariaLabel = `${legLabel} ${valueText} — ${sourceLabel} — ${tooltip}`

  // Style variants based on status
  const { container, extraIcon } = chipStylesForStatus(leg.status, config)

  return (
    <span
      className={container}
      role="status"
      tabIndex={0}
      aria-label={ariaLabel}
      title={tooltip}
      data-status={leg.status}
      data-kind={kind}
      data-source={leg.source}
    >
      <LegIcon size={13} className={config.color} aria-hidden="true" />
      <span className="text-xs font-medium">{legLabel}</span>
      {valueText && (
        <span className="text-xs tabular-nums opacity-90">{valueText}</span>
      )}
      {extraIcon && (
        <span className="inline-flex items-center" aria-hidden="true">{extraIcon}</span>
      )}
      <span
        className="ml-0.5 opacity-70 inline-flex items-center"
        aria-hidden="true"
        title={sourceLabel}
      >
        <SourceIcon size={11} />
      </span>
    </span>
  )
}

/** Per-status visual treatment: base confirmed + overrides for pending/rejected/cancel_failed. */
function chipStylesForStatus(
  status: RiskLegStatusCode,
  config: typeof LEG_CONFIG[LegKind],
): { container: string; extraIcon: React.ReactNode | null } {
  const base = 'inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full border text-xs'

  if (status === 'pending') {
    return {
      container: `${base} ${config.color} bg-white/5 border-dashed border-white/30 animate-pulse`,
      extraIcon: <Loader2 size={11} className="animate-spin" />,
    }
  }
  if (status === 'rejected') {
    return {
      container: `${base} text-red-400 bg-red-500/10 border-red-500/40`,
      extraIcon: <XCircle size={11} className="text-red-400" />,
    }
  }
  if (status === 'cancel_failed') {
    return {
      container: `${base} text-amber-400 bg-amber-500/10 border-amber-500/40`,
      extraIcon: <AlertTriangle size={11} className="text-amber-400" />,
    }
  }
  // confirmed (default)
  return {
    container: `${base} ${config.color} ${config.bgConfirmed} ${config.borderConfirmed}`,
    extraIcon: null,
  }
}

/** True when leg should produce a visible chip. */
function isLegVisible(leg: RiskLegStatus | null): leg is RiskLegStatus {
  if (!leg) return false
  if (leg.status === 'cleared') return false
  // Confirmed legs require a value; pending/rejected/cancel_failed render regardless.
  if (leg.status === 'confirmed' && leg.value == null) return false
  return true
}

export default function RiskStateBadge({
  tp,
  sl,
  trailing,
  compact = false,
}: RiskStateBadgeProps) {
  const showTp = isLegVisible(tp)
  const showSl = isLegVisible(sl)
  const showTrail = isLegVisible(trailing)

  // Nothing to render — caller can fall back to legacy display
  if (!showTp && !showSl && !showTrail) return null

  const layout = compact
    ? 'flex flex-col items-start gap-1'
    : 'flex flex-row flex-wrap items-center gap-1.5'

  return (
    <div
      className={layout}
      role="group"
      aria-label="Risk state"
      data-testid="risk-state-badge"
      data-compact={compact ? 'true' : 'false'}
    >
      {showTp && <RiskChip leg={tp} kind="tp" />}
      {showSl && <RiskChip leg={sl} kind="sl" />}
      {showTrail && <RiskChip leg={trailing} kind="trailing" />}
    </div>
  )
}
