/**
 * Slide-over panel for editing TP/SL/Trailing Stop on open positions.
 * Matches the BotTradeHistoryModal pattern — full-screen overlay, centered card.
 * Backend integration pending (Issue #120).
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { X, Target, ShieldAlert, TrendingUp, AlertTriangle, Info, Zap, Bot } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { ExchangeIcon } from './ExchangeLogo'
import useIsMobile from '../../hooks/useIsMobile'
import useSwipeToClose from '../../hooks/useSwipeToClose'

/* ── Types ──────────────────────────────────────────────── */

interface PositionData {
  trade_id: number
  symbol: string
  side: string
  entry_price: number
  current_price: number
  leverage: number
  exchange: string
  bot_name?: string | null
  demo_mode?: boolean
  take_profit?: number | null
  stop_loss?: number | null
  trailing_stop_active?: boolean
  trailing_stop_price?: number | null
  trailing_stop_distance_pct?: number | null
}

interface EditPositionPanelProps {
  position: PositionData
  onClose: () => void
  onSave: (data: {
    take_profit: number | null
    stop_loss: number | null
    trailing_stop: { callback_pct: number; trigger_price: number } | null
  }) => Promise<void>
}

/* ── Helpers ────────────────────────────────────────────── */

const TRAILING_EXCHANGES = ['bitget', 'bingx']

function pctFromEntry(entry: number, price: number, isLong: boolean): string {
  if (!entry || !price) return '0.00'
  const pct = isLong
    ? ((price - entry) / entry) * 100
    : ((entry - price) / entry) * 100
  return pct.toFixed(2)
}

function priceFromPct(entry: number, pct: number, isLong: boolean): number {
  return isLong
    ? entry * (1 + pct / 100)
    : entry * (1 - pct / 100)
}

/* ── Component ──────────────────────────────────────────── */

export default function EditPositionPanel({ position, onClose, onSave }: EditPositionPanelProps) {
  const { t } = useTranslation()
  const isMobile = useIsMobile()
  const swipe = useSwipeToClose({ onClose, enabled: isMobile })
  const isLong = position.side.toLowerCase() === 'long'
  const exchangeName = position.exchange.charAt(0).toUpperCase() + position.exchange.slice(1)
  const hasNativeTrailing = TRAILING_EXCHANGES.includes(position.exchange.toLowerCase())

  /* ── State ── */
  const [tpPrice, setTpPrice] = useState(position.take_profit?.toString() ?? '')
  const [slPrice, setSlPrice] = useState(position.stop_loss?.toString() ?? '')
  const [tpPct, setTpPct] = useState(
    position.take_profit
      ? pctFromEntry(position.entry_price, position.take_profit, isLong)
      : ''
  )
  const [slPct, setSlPct] = useState(
    position.stop_loss
      ? pctFromEntry(position.entry_price, position.stop_loss, isLong)
      : ''
  )
  const [trailingEnabled, setTrailingEnabled] = useState(position.trailing_stop_active ?? false)
  const [trailingAtr, setTrailingAtr] = useState(2.5)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  /* ── Sync price <-> pct ── */
  const handleTpPrice = useCallback((val: string) => {
    setTpPrice(val)
    const num = parseFloat(val)
    if (!isNaN(num) && num > 0) {
      setTpPct(pctFromEntry(position.entry_price, num, isLong))
    } else {
      setTpPct('')
    }
  }, [position.entry_price, isLong])

  const handleTpPct = useCallback((val: string) => {
    setTpPct(val)
    const num = parseFloat(val)
    if (!isNaN(num) && num > 0) {
      setTpPrice(priceFromPct(position.entry_price, num, isLong).toFixed(2))
    } else {
      setTpPrice('')
    }
  }, [position.entry_price, isLong])

  const handleSlPrice = useCallback((val: string) => {
    setSlPrice(val)
    const num = parseFloat(val)
    if (!isNaN(num) && num > 0) {
      setSlPct(pctFromEntry(position.entry_price, num, !isLong))
    } else {
      setSlPct('')
    }
  }, [position.entry_price, isLong])

  const handleSlPct = useCallback((val: string) => {
    setSlPct(val)
    const num = parseFloat(val)
    if (!isNaN(num) && num > 0) {
      setSlPrice(priceFromPct(position.entry_price, num, !isLong).toFixed(2))
    } else {
      setSlPrice('')
    }
  }, [position.entry_price, isLong])

  /* ── Validation ── */
  const validation = useMemo(() => {
    const issues: string[] = []
    const tp = parseFloat(tpPrice)
    const sl = parseFloat(slPrice)

    if (tpPrice && !isNaN(tp)) {
      if (isLong && tp <= position.entry_price) {
        issues.push(t('editPosition.tpBelowEntry', 'TP muss über dem Einstiegspreis liegen (Long)'))
      }
      if (!isLong && tp >= position.entry_price) {
        issues.push(t('editPosition.tpAboveEntry', 'TP muss unter dem Einstiegspreis liegen (Short)'))
      }
    }
    if (slPrice && !isNaN(sl)) {
      if (isLong && sl >= position.entry_price) {
        issues.push(t('editPosition.slAboveEntry', 'SL muss unter dem Einstiegspreis liegen (Long)'))
      }
      if (!isLong && sl <= position.entry_price) {
        issues.push(t('editPosition.slBelowEntry', 'SL muss über dem Einstiegspreis liegen (Short)'))
      }
    }
    return issues
  }, [tpPrice, slPrice, position.entry_price, isLong, t])

  /* ── ESC handler ── */
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [onClose])

  /* ── Save ── */
  const handleSave = async () => {
    if (validation.length > 0) return
    setSaving(true)
    setError(null)
    try {
      const tp = tpPrice ? parseFloat(tpPrice) : null
      const sl = slPrice ? parseFloat(slPrice) : null
      const trailing = trailingEnabled ? {
        callback_pct: trailingAtr,
        trigger_price: position.entry_price * (isLong ? 1.02 : 0.98),
      } : null
      await onSave({ take_profit: tp, stop_loss: sl, trailing_stop: trailing })
      onClose()
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Fehler beim Speichern')
    } finally {
      setSaving(false)
    }
  }

  const isPnlPositive = position.current_price > position.entry_price
    ? isLong
    : !isLong

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 backdrop-blur-md"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
    >
      <div
        ref={swipe.ref}
        style={swipe.style}
        className="bg-[#0b0f19] rounded-2xl max-w-lg w-full mx-2 sm:mx-4 my-2 sm:my-3 max-h-[80vh] sm:max-h-[85vh] lg:max-h-[90vh] flex flex-col border border-white/10 shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* ── Swipe indicator (mobile) ── */}
        {isMobile && (
          <div className="flex justify-center pt-2 pb-1">
            <div className="w-10 h-1 rounded-full bg-white/20" />
          </div>
        )}

        {/* ── Header ── */}
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-white/5 shrink-0">
          <div className="flex items-center gap-3">
            <div className="p-1.5 rounded-xl bg-white/5">
              <ExchangeIcon exchange={position.exchange} size={20} />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="text-white font-semibold text-base">{position.symbol}</span>
                <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${
                  isLong ? 'bg-emerald-500/15 text-emerald-400' : 'bg-red-500/15 text-red-400'
                }`}>
                  {position.side.toUpperCase()}
                </span>
                {position.demo_mode && (
                  <span className="text-[9px] font-semibold px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-400">DEMO</span>
                )}
              </div>
              <span className="text-xs text-gray-500">
                {position.bot_name && `${position.bot_name} · `}{position.leverage}x · {exchangeName}
              </span>
            </div>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-white transition-colors p-1.5 rounded-lg hover:bg-white/5">
            <X size={20} />
          </button>
        </div>

        {/* ── Scrollable content ── */}
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5">

          {/* ── Price overview ── */}
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 sm:gap-3">
            <div className="bg-white/[0.03] rounded-xl p-3 border border-white/5">
              <div className="text-[9px] text-gray-500 uppercase tracking-wider mb-1">{t('trades.entryPrice', 'Einstieg')}</div>
              <div className="text-white font-semibold tabular-nums">${position.entry_price.toLocaleString()}</div>
            </div>
            <div className="bg-white/[0.03] rounded-xl p-3 border border-white/5">
              <div className="text-[9px] text-gray-500 uppercase tracking-wider mb-1">{t('portfolio.currentPrice', 'Aktuell')}</div>
              <div className="text-white font-semibold tabular-nums">${position.current_price.toLocaleString()}</div>
            </div>
            <div className={`rounded-xl p-3 border ${isPnlPositive ? 'bg-emerald-500/[0.06] border-emerald-500/20' : 'bg-red-500/[0.06] border-red-500/20'}`}>
              <div className="text-[9px] text-gray-500 uppercase tracking-wider mb-1">PnL</div>
              <div className={`font-semibold tabular-nums ${isPnlPositive ? 'text-emerald-400' : 'text-red-400'}`}>
                {isPnlPositive ? '+' : ''}{pctFromEntry(position.entry_price, position.current_price, isLong)}%
              </div>
            </div>
          </div>

          {/* ── Take Profit ── */}
          <div className="space-y-2.5">
            <div className="flex items-center gap-2">
              <Target size={14} className="text-emerald-400" />
              <span className="text-sm font-medium text-white">Take Profit</span>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-[9px] text-gray-500 uppercase tracking-wider block mb-1">{t('editPosition.price', 'Preis')}</label>
                <div className="relative">
                  <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500 text-sm">$</span>
                  <input
                    type="number"
                    value={tpPrice}
                    onChange={(e) => handleTpPrice(e.target.value)}
                    placeholder="--"
                    step="0.01"
                    className="w-full bg-white/[0.04] border border-white/10 rounded-lg px-3 pl-7 py-2 text-sm text-white tabular-nums placeholder:text-gray-600 focus:outline-none focus:border-emerald-500/50 focus:ring-1 focus:ring-emerald-500/20 transition-colors"
                  />
                </div>
              </div>
              <div>
                <label className="text-[9px] text-gray-500 uppercase tracking-wider block mb-1">{t('editPosition.percent', 'Prozent')}</label>
                <div className="relative">
                  <input
                    type="number"
                    value={tpPct}
                    onChange={(e) => handleTpPct(e.target.value)}
                    placeholder="--"
                    step="0.1"
                    className="w-full bg-white/[0.04] border border-white/10 rounded-lg px-3 pr-7 py-2 text-sm text-white tabular-nums placeholder:text-gray-600 focus:outline-none focus:border-emerald-500/50 focus:ring-1 focus:ring-emerald-500/20 transition-colors"
                  />
                  <span className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 text-sm">%</span>
                </div>
              </div>
            </div>
          </div>

          {/* ── Stop Loss ── */}
          <div className="space-y-2.5">
            <div className="flex items-center gap-2">
              <ShieldAlert size={14} className="text-red-400" />
              <span className="text-sm font-medium text-white">Stop Loss</span>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-[9px] text-gray-500 uppercase tracking-wider block mb-1">{t('editPosition.price', 'Preis')}</label>
                <div className="relative">
                  <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500 text-sm">$</span>
                  <input
                    type="number"
                    value={slPrice}
                    onChange={(e) => handleSlPrice(e.target.value)}
                    placeholder="--"
                    step="0.01"
                    className="w-full bg-white/[0.04] border border-white/10 rounded-lg px-3 pl-7 py-2 text-sm text-white tabular-nums placeholder:text-gray-600 focus:outline-none focus:border-red-500/50 focus:ring-1 focus:ring-red-500/20 transition-colors"
                  />
                </div>
              </div>
              <div>
                <label className="text-[9px] text-gray-500 uppercase tracking-wider block mb-1">{t('editPosition.percent', 'Prozent')}</label>
                <div className="relative">
                  <input
                    type="number"
                    value={slPct}
                    onChange={(e) => handleSlPct(e.target.value)}
                    placeholder="--"
                    step="0.1"
                    className="w-full bg-white/[0.04] border border-white/10 rounded-lg px-3 pl-7 py-2 text-sm text-white tabular-nums placeholder:text-gray-600 focus:outline-none focus:border-red-500/50 focus:ring-1 focus:ring-red-500/20 transition-colors"
                  />
                  <span className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 text-sm">%</span>
                </div>
              </div>
            </div>
          </div>

          {/* ── Divider ── */}
          <div className="border-t border-white/5" />

          {/* ── Trailing Stop ── */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <TrendingUp size={14} className="text-blue-400" />
                <span className="text-sm font-medium text-white">Trailing Stop</span>
              </div>
              <button
                onClick={() => setTrailingEnabled(!trailingEnabled)}
                className={`relative w-10 h-5 rounded-full transition-colors duration-200 ${
                  trailingEnabled ? 'bg-emerald-500' : 'bg-white/10'
                }`}
              >
                <span className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform duration-200 ${
                  trailingEnabled ? 'translate-x-5' : 'translate-x-0'
                }`} />
              </button>
            </div>

            {trailingEnabled && (
              <div className="space-y-3 animate-in fade-in slide-in-from-top-1 duration-200">
                {/* ATR Slider */}
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <label className="text-[9px] text-gray-500 uppercase tracking-wider">
                      {t('editPosition.trailDistance', 'Nachlauf-Abstand (ATR)')}
                    </label>
                    <span className="text-sm font-semibold text-white tabular-nums">{trailingAtr.toFixed(1)}x</span>
                  </div>
                  <input
                    type="range"
                    min="1.0"
                    max="5.0"
                    step="0.1"
                    value={trailingAtr}
                    onChange={(e) => setTrailingAtr(parseFloat(e.target.value))}
                    className="w-full h-1.5 bg-white/10 rounded-full appearance-none cursor-pointer accent-emerald-500
                      [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:h-4 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-emerald-400 [&::-webkit-slider-thumb]:shadow-lg [&::-webkit-slider-thumb]:shadow-emerald-500/30 [&::-webkit-slider-thumb]:cursor-pointer
                      [&::-moz-range-thumb]:w-4 [&::-moz-range-thumb]:h-4 [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:bg-emerald-400 [&::-moz-range-thumb]:border-0 [&::-moz-range-thumb]:cursor-pointer"
                  />
                  <div className="flex justify-between text-[9px] text-gray-600 mt-1 tabular-nums">
                    <span>1.0x</span>
                    <span>2.0x</span>
                    <span>3.0x</span>
                    <span>4.0x</span>
                    <span>5.0x</span>
                  </div>
                </div>

                {/* Recommendation hint (placeholder) */}
                <div className="bg-blue-500/[0.06] border border-blue-500/15 rounded-lg px-3 py-2 flex items-start gap-2">
                  <Info size={12} className="text-blue-400 shrink-0 mt-0.5" />
                  <span className="text-xs text-blue-300/80">
                    {t(
                      'editPosition.trailingHint',
                      'Die Empfehlung basiert auf deinen bisherigen Trades und wird berechnet sobald genug Daten vorliegen (min. 10 Trades).'
                    )}
                  </span>
                </div>

                {/* Exchange type indicator */}
                <div className="flex items-center gap-2 text-xs">
                  {hasNativeTrailing ? (
                    <>
                      <Zap size={12} className="text-amber-400 shrink-0" />
                      <span className="text-gray-400">
                        Exchange-nativ ({exchangeName}) — {t('editPosition.nativeHint', 'funktioniert auch wenn der Bot offline ist')}
                      </span>
                    </>
                  ) : (
                    <>
                      <Bot size={12} className="text-blue-400 shrink-0" />
                      <span className="text-gray-400">
                        Bot-überwacht (Software) — {t('editPosition.softwareHint', 'Bot muss online sein')}
                      </span>
                    </>
                  )}
                </div>
              </div>
            )}
          </div>

          {/* ── Validation errors ── */}
          {validation.length > 0 && (
            <div className="bg-red-500/[0.08] border border-red-500/20 rounded-lg px-3 py-2 space-y-1">
              {validation.map((msg, i) => (
                <div key={i} className="flex items-center gap-2 text-xs text-red-400">
                  <AlertTriangle size={12} className="shrink-0" />
                  <span>{msg}</span>
                </div>
              ))}
            </div>
          )}

          {/* ── Info notice ── */}
          {(tpPrice || slPrice) && !trailingEnabled && (
            <p className="text-[11px] text-gray-500 leading-relaxed">
              {t(
                'editPosition.strategyExitNote',
                'Hinweis: Wenn TP/SL gesetzt ist, wird der Strategie-Exit deaktiviert. Die Exchange-Orders haben Vorrang.'
              )}
            </p>
          )}

          {/* ── Error ── */}
          {error && (
            <div className="bg-red-500/[0.08] border border-red-500/20 rounded-lg p-3 text-[11px] text-red-400">
              {error}
            </div>
          )}
        </div>

        {/* ── Footer ── */}
        <div className="px-5 py-3.5 border-t border-white/5 flex items-center justify-end gap-3 shrink-0">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm rounded-lg bg-white/5 hover:bg-white/10 text-gray-300 transition-colors"
          >
            {t('common.cancel', 'Abbrechen')}
          </button>
          <button
            onClick={handleSave}
            disabled={saving || validation.length > 0}
            className={`px-5 py-2 text-sm rounded-lg font-medium transition-all flex items-center gap-2 ${
              saving || validation.length > 0
                ? 'bg-emerald-500/20 text-emerald-500/50 cursor-not-allowed'
                : 'bg-emerald-500 hover:bg-emerald-400 text-white shadow-lg shadow-emerald-500/20'
            }`}
          >
            {saving && <div className="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin" />}
            {t('editPosition.save', 'Übernehmen')}
          </button>
        </div>
      </div>
    </div>
  )
}
