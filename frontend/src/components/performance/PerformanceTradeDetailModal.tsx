import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toBlob } from 'html-to-image'
import { Share2, X } from 'lucide-react'
import { ExchangeIcon } from '../ui/ExchangeLogo'
import PnlCell from '../ui/PnlCell'
import { useThemeStore } from '../../stores/themeStore'
import { useToastStore } from '../../stores/toastStore'
import useIsMobile from '../../hooks/useIsMobile'
import useSwipeToClose from '../../hooks/useSwipeToClose'
import { formatDate } from '../../utils/dateUtils'
import { formatPnlPercent, type AffiliateLink, type BotDetailRecentTrade } from './types'

interface Props {
  trade: BotDetailRecentTrade
  exchange: string | undefined
  affiliateLink: AffiliateLink | null
  onClose: () => void
}

/**
 * Modal that shows a single closed trade in a shareable format. Mirrors the
 * trade-detail modal used on the Bots page but driven from BotPerformance state.
 */
export default function PerformanceTradeDetailModal({ trade, exchange, affiliateLink, onClose }: Props) {
  const { t } = useTranslation()
  const theme = useThemeStore((s) => s.theme)
  const isMobile = useIsMobile()
  const swipe = useSwipeToClose({ onClose, enabled: isMobile })
  const tradeCardRef = useRef<HTMLDivElement>(null)
  const [copied, setCopied] = useState(false)
  const copiedTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Clear pending "copied" reset timer on unmount (#332).
  useEffect(() => {
    return () => {
      if (copiedTimerRef.current) {
        clearTimeout(copiedTimerRef.current)
        copiedTimerRef.current = null
      }
    }
  }, [])

  const handleShare = async () => {
    if (!tradeCardRef.current) return
    try {
      const isMobileDevice = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent)
      const el = tradeCardRef.current

      if (!isMobileDevice) {
        // Desktop: pass a Promise to ClipboardItem so the async toBlob
        // stays within the user-gesture window (Chrome requirement)
        const blobPromise = toBlob(el, {
          pixelRatio: 2,
          backgroundColor: theme === 'light' ? '#f8fafc' : '#0b0f19',
        }).then(b => {
          if (!b) throw new Error('toBlob returned null')
          return new Blob([b], { type: 'image/png' })
        })
        await navigator.clipboard.write([
          new ClipboardItem({ 'image/png': blobPromise }),
        ])
        setCopied(true)
        if (copiedTimerRef.current) clearTimeout(copiedTimerRef.current)
        copiedTimerRef.current = setTimeout(() => {
          setCopied(false)
          copiedTimerRef.current = null
        }, 2000)
        return
      }

      // Mobile: native share
      const blob = await toBlob(el, {
        pixelRatio: 2,
        backgroundColor: theme === 'light' ? '#f8fafc' : '#0b0f19',
      })
      if (!blob) return
      if (navigator.share && navigator.canShare) {
        const file = new File([blob], 'trade.png', { type: 'image/png' })
        const pnlStr = trade.pnl_percent >= 0 ? `+${trade.pnl_percent.toFixed(2)}%` : `${trade.pnl_percent.toFixed(2)}%`
        if (navigator.canShare({ files: [file] })) {
          await navigator.share({
            title: `${trade.symbol} ${trade.side.toUpperCase()} ${pnlStr}`,
            text: affiliateLink?.affiliate_url || 'Edge Bots by Trading Department',
            files: [file],
          })
        }
      }
    } catch (err) {
      if ((err as DOMException).name !== 'AbortError') {
        console.error('Failed to share image:', err)
        useToastStore.getState().addToast('error', t('common.error'))
      }
    }
  }

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center">
      <button
        type="button"
        aria-label={t('common.close')}
        onClick={onClose}
        className="absolute inset-0 w-full h-full bg-black/70 backdrop-blur-md border-0 appearance-none cursor-default"
      />
      <div
        ref={swipe.ref}
        style={swipe.style}
        role="dialog"
        aria-modal="true"
        aria-label={trade.symbol}
        onKeyDown={(e) => { if (e.key === 'Escape') onClose() }}
        className="relative bg-[#0f1420] rounded-2xl max-w-lg w-full mx-4 border border-white/10 shadow-2xl overflow-hidden"
      >
        {isMobile && (
          <div className="flex justify-center pt-2 pb-1 lg:hidden">
            <div className="w-10 h-1 rounded-full bg-white/20" />
          </div>
        )}
        {/* Modal Header with Copy Button */}
        <div className="flex items-center justify-between px-7 pt-7 pb-0">
          <div className="flex items-center gap-3">
            <h3 className="text-xl font-bold text-white">{trade.symbol}</h3>
            <span className={`px-3 py-1 rounded-lg text-xs font-bold ${
              trade.side === 'long' ? 'bg-emerald-500/15 text-profit border border-emerald-500/20' : 'bg-red-500/15 text-loss border border-red-500/20'
            }`}>
              {trade.side === 'long' ? '+ LONG' : '- SHORT'}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={handleShare}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg transition-all border ${
                copied
                  ? 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20'
                  : 'text-gray-400 hover:text-white bg-white/5 hover:bg-white/10 border-white/5'
              }`}
              title={t('bots.shareImage')}
            >
              <Share2 size={14} />
              {copied ? t('bots.copied') : t('bots.shareImage')}
            </button>
            <button onClick={onClose} className="hidden sm:block p-1.5 rounded-lg text-gray-400 hover:text-white hover:bg-white/5 transition-all" aria-label="Close">
              <X size={20} />
            </button>
          </div>
        </div>

        {/* Capturable Card Content */}
        <div ref={tradeCardRef} className="p-5">
          {/* Header: Exchange logo + Symbol */}
          <div className="flex items-center gap-2 mb-1">
            {exchange && <ExchangeIcon exchange={exchange} size={18} />}
            <span className="text-lg font-bold text-white">{trade.symbol}</span>
          </div>
          {/* Perp | Side | Leverage | Date */}
          <div className="flex items-center gap-2 text-sm text-gray-400 mb-4">
              <span>Perp</span>
              <span className="text-gray-600">|</span>
              <span className={trade.side === 'long' ? 'text-emerald-400 font-medium' : 'text-red-400 font-medium'}>
                {trade.side === 'long' ? '+ LONG' : '- SHORT'}
              </span>
              {trade.leverage && (
                <>
                  <span className="text-gray-600">|</span>
                  <span className="text-white font-medium">{trade.leverage}x</span>
                </>
              )}
              <span className="text-xs text-gray-500" style={{ marginLeft: 'auto' }}>{formatDate(trade.entry_time)}</span>
          </div>

          {/* PnL - Hero */}
          <div className="text-center py-5 mb-4">
            <div className={`text-5xl font-bold tracking-tight ${trade.pnl_percent >= 0 ? 'text-profit' : 'text-loss'}`}>
              {formatPnlPercent(trade.pnl_percent)}
            </div>
            <div className={`text-lg font-semibold mt-1 ${trade.pnl >= 0 ? 'text-profit/70' : 'text-loss/70'}`}>
              <PnlCell
                pnl={trade.pnl}
                fees={trade.fees ?? 0}
                fundingPaid={trade.funding_paid ?? 0}
                status={trade.status}
                className={`text-lg font-semibold ${trade.pnl >= 0 ? 'text-profit/70' : 'text-loss/70'}`}
              />
            </div>
          </div>

          {/* Entry / Exit Price */}
          <div className="grid grid-cols-2 gap-4 max-w-xs mx-auto mb-4">
            <div className="text-center">
              <div className="text-xs text-gray-400 mb-1">{t('bots.entryPrice')}</div>
              <div className="text-white font-semibold text-lg">${trade.entry_price.toLocaleString()}</div>
            </div>
            <div className="text-center">
              <div className="text-xs text-gray-400 mb-1">{t('bots.exitPrice')}</div>
              <div className="text-white font-semibold text-lg">
                {trade.exit_price ? `$${trade.exit_price.toLocaleString()}` : '--'}
              </div>
            </div>
          </div>

          {/* Footer: Branding + Affiliate */}
          <div className="pt-3 border-t border-white/5">
            <div className="text-xs text-gray-500">Edge Bots by Trading Department</div>
            {affiliateLink && (
              <>
                {affiliateLink.label && <div className="text-xs text-gray-400 mt-0.5">{affiliateLink.label}</div>}
                <div className="text-xs text-primary-400 font-medium mt-0.5">{affiliateLink.affiliate_url}</div>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
