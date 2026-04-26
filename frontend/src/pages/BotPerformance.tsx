import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toBlob } from 'html-to-image'
import { useAffiliateLinks, useBotComparePerformance, useBotStatistics } from '../api/queries'
import { useToastStore } from '../stores/toastStore'
import { useFilterStore } from '../stores/filterStore'
import { useThemeStore } from '../stores/themeStore'
import { SkeletonChart, SkeletonTable } from '../components/ui/Skeleton'
import useIsMobile from '../hooks/useIsMobile'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
import { formatChartDate } from '../utils/dateUtils'
import BotCard from '../components/performance/BotCard'
import SmallMultipleCard from '../components/performance/SmallMultipleCard'
import BotDetailPanel from '../components/performance/BotDetailPanel'
import PerformancePageHeader from '../components/performance/PerformancePageHeader'
import PerformanceTradeDetailModal from '../components/performance/PerformanceTradeDetailModal'
import {
  BOT_COLORS,
  type AffiliateLink,
  type BotCompareData,
  type BotDetailRecentTrade,
  type BotDetailStats,
} from '../components/performance/types'

export default function BotPerformance() {
  const { t } = useTranslation()
  useDocumentTitle(t('nav.performance'))
  const { demoFilter } = useFilterStore()
  const theme = useThemeStore((s) => s.theme)
  const chartGridColor = theme === 'light' ? '#e2e8f0' : '#374151'
  const chartTickColor = theme === 'light' ? '#64748b' : '#9ca3af'
  const refColor = theme === 'light' ? '#cbd5e1' : '#6b7280'
  const isMobile = useIsMobile()
  const [days, setDays] = useState(30)
  const [selectedBot, setSelectedBot] = useState<number | null>(null)
  const [hoveredBot, setHoveredBot] = useState<number | null>(null)

  // Data fetching via React Query
  const { data: rawCompareData, isLoading: loading, error: compareError } = useBotComparePerformance(days, demoFilter)
  const compareData: BotCompareData[] = rawCompareData || []
  const { data: rawBotDetail, error: detailQueryError } = useBotStatistics(selectedBot || 0, days, demoFilter)
  const botDetail: BotDetailStats | null = selectedBot ? (rawBotDetail || null) : null
  const { data: affiliateLinksData = [] } = useAffiliateLinks()
  const affiliateLinks: AffiliateLink[] = affiliateLinksData
  const error = compareError ? t('performance.loadError') : ''
  const detailError = detailQueryError ? t('performance.detailError') : ''
  const [viewMode, setViewMode] = useState<'cards' | 'grid'>('cards')
  const [selectedTrade, setSelectedTrade] = useState<BotDetailRecentTrade | null>(null)
  // Tracks the "copied" flag-reset timer for the share handler so we can
  // clear it on unmount and avoid a state-update-after-unmount warning when
  // the user navigates away within the 2s window (#332).
  const copiedTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  // Lazy-mount mobile share capture: only render the card for the trade
  // currently being shared. Previously we pre-rendered every closed trade in
  // a hidden div at -9999px — a performance drain since React re-ran that
  // subtree on every parent state change.
  const [sharingTrade, setSharingTrade] = useState<BotDetailRecentTrade | null>(null)
  const shareResolveRef = useRef<((el: HTMLDivElement | null) => void) | null>(null)

  // Clear any pending "copied" flag-reset timer on unmount so the deferred
  // setFlag(false) does not fire against a stale component.
  useEffect(() => {
    return () => {
      if (copiedTimerRef.current) {
        clearTimeout(copiedTimerRef.current)
        copiedTimerRef.current = null
      }
    }
  }, [])

  const handleMobileDirectShare = useCallback(async (trade: BotDetailRecentTrade) => {
    try {
      // Lazy-mount the hidden capture card for this trade and wait for
      // the callback ref to fire once React has committed the node to
      // the DOM. This keeps the share-capture subtree out of the DOM
      // until the user actually invokes share.
      const mountPromise = new Promise<HTMLDivElement | null>((resolve) => {
        shareResolveRef.current = resolve
      })
      setSharingTrade(trade)
      const ref = await mountPromise
      if (!ref) { setSharingTrade(null); setSelectedTrade(trade); return }
      const blob = await toBlob(ref, {
        pixelRatio: 2,
        backgroundColor: theme === 'light' ? '#f8fafc' : '#0b0f19',
      })
      // Unmount the capture div as soon as the blob is produced.
      setSharingTrade(null)
      if (!blob) { setSelectedTrade(trade); return }
      const file = new File([blob], 'trade.png', { type: 'image/png' })
      const pnlStr = trade.pnl_percent >= 0 ? `+${trade.pnl_percent.toFixed(2)}%` : `${trade.pnl_percent.toFixed(2)}%`
      if (navigator.share && navigator.canShare && navigator.canShare({ files: [file] })) {
        const botEx = compareData.find(b => b.bot_id === selectedBot)?.exchange_type
        const aLink = botEx ? affiliateLinks.find(l => l.exchange_type === botEx) : null
        await navigator.share({
          title: `${trade.symbol} ${trade.side.toUpperCase()} ${pnlStr}`,
          text: aLink?.affiliate_url || 'Edge Bots by Trading Department',
          files: [file],
        })
      } else {
        // Fallback: open modal
        setSelectedTrade(trade)
      }
    } catch (err) {
      setSharingTrade(null)
      if ((err as DOMException).name !== 'AbortError') {
        console.error('Failed to share image:', err)
        useToastStore.getState().addToast('error', t('common.error'))
      }
    }
  }, [theme, compareData, selectedBot, affiliateLinks, t])

  // Build bot detail chart data
  const botChartData = useMemo(() => {
    if (!botDetail) return []
    let cumulative = 0
    return botDetail.daily_series.map((d) => {
      cumulative += d.pnl
      return {
        date: formatChartDate(d.date),
        dailyPnl: Number(d.pnl.toFixed(2)),
        fees: Number(Math.abs(d.fees || 0).toFixed(2)),
        funding: Number(Math.abs(d.funding || 0).toFixed(2)),
        cumulativePnl: Number(cumulative.toFixed(2)),
      }
    })
  }, [botDetail])

  // Shared Y-axis domain for Small Multiples (fair comparison)
  const sharedYDomain = useMemo<[number, number]>(() => {
    const allValues = compareData.flatMap(b => b.series.map(s => s.cumulative_pnl))
    if (allValues.length === 0) return [-10, 10]
    const min = Math.min(...allValues, 0)
    const max = Math.max(...allValues, 0)
    const pad = Math.max(Math.abs(max - min) * 0.1, 5)
    return [Math.floor(min - pad), Math.ceil(max + pad)]
  }, [compareData])

  const handleCardClick = (botId: number) => {
    setSelectedBot(selectedBot === botId ? null : botId)
  }

  const selectedBotData = selectedBot ? compareData.find(b => b.bot_id === selectedBot) ?? null : null
  const selectedBotExchange = selectedBotData?.exchange_type || ''
  const selectedAffiliateLink = selectedBotExchange
    ? affiliateLinks.find(l => l.exchange_type === selectedBotExchange) ?? null
    : null

  return (
    <div className="animate-in">
      <PerformancePageHeader
        viewMode={viewMode}
        days={days}
        onViewModeChange={setViewMode}
        onDaysChange={setDays}
      />

      {/* Error */}
      {error && (
        <div role="alert" className="mb-4 p-3 bg-red-500/10 border border-red-500/20 rounded-xl text-red-400 text-sm">
          {error}
        </div>
      )}

      {loading ? (
        <div className="space-y-6">
          <SkeletonChart height="h-[400px]" />
          <SkeletonTable rows={4} cols={7} />
        </div>
      ) : compareData.length === 0 ? (
        <div className="glass-card rounded-xl p-16 text-center">
          <div className="text-gray-500 text-sm">{t('performance.noData')}</div>
        </div>
      ) : (
        <>
          {viewMode === 'cards' ? (
            /* ── Konzept 1: Bot Cards + Interactive Chart ──── */
            <div className="mb-5">
              <div className="flex flex-wrap gap-3">
                {compareData.map((bot, i) => (
                  <BotCard
                    key={bot.bot_id}
                    bot={bot}
                    color={BOT_COLORS[i % BOT_COLORS.length]}
                    isSelected={selectedBot === bot.bot_id}
                    isHovered={hoveredBot === bot.bot_id}
                    onClick={() => handleCardClick(bot.bot_id)}
                    onMouseEnter={() => setHoveredBot(bot.bot_id)}
                    onMouseLeave={() => setHoveredBot(null)}
                    index={i}
                  />
                ))}
              </div>
            </div>
          ) : (
            /* ── Konzept 2: Small Multiples Grid ─────────── */
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">
              {compareData.map((bot, i) => (
                <SmallMultipleCard
                  key={bot.bot_id}
                  bot={bot}
                  color={BOT_COLORS[i % BOT_COLORS.length]}
                  yDomain={sharedYDomain}
                  chartGridColor={chartGridColor}
                  chartTickColor={chartTickColor}
                  isSelected={selectedBot === bot.bot_id}
                  onClick={() => handleCardClick(bot.bot_id)}
                />
              ))}
            </div>
          )}

          {/* Detail Error */}
          {detailError && (
            <div role="alert" className="mb-4 p-3 bg-red-500/10 border border-red-500/20 rounded-xl text-red-400 text-sm">
              {detailError}
            </div>
          )}

          {/* ── Bot Detail Panel ─────────────────────────── */}
          {botDetail && (
            <BotDetailPanel
              botDetail={botDetail}
              selectedBotData={selectedBotData}
              affiliateLink={selectedAffiliateLink}
              botChartData={botChartData}
              isMobile={isMobile}
              chartGridColor={chartGridColor}
              chartTickColor={chartTickColor}
              refColor={refColor}
              sharingTrade={sharingTrade}
              shareResolveRef={shareResolveRef}
              onSelectTrade={setSelectedTrade}
              onMobileDirectShare={handleMobileDirectShare}
            />
          )}
        </>
      )}

      {/* Trade Detail Modal */}
      {selectedTrade && (
        <PerformanceTradeDetailModal
          trade={selectedTrade}
          exchange={selectedBotExchange || undefined}
          affiliateLink={selectedAffiliateLink}
          onClose={() => setSelectedTrade(null)}
        />
      )}
    </div>
  )
}
