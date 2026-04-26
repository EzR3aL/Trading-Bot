import { useState, useEffect, useRef, Fragment } from 'react'
import { toBlob } from 'html-to-image'
import {
  Activity,
  ArrowDownRight,
  ArrowUpRight,
  ChevronRight,
  RefreshCw,
  Share2,
  Shield,
  X,
} from 'lucide-react'
import api from '../../api/client'
import { ExchangeIcon } from '../ui/ExchangeLogo'
import PnlCell from '../ui/PnlCell'
import ExitReasonBadge from '../ui/ExitReasonBadge'
import MobileTradeCard from '../ui/MobileTradeCard'
import SizeValue from '../ui/SizeValue'
import { useThemeStore } from '../../stores/themeStore'
import { useToastStore } from '../../stores/toastStore'
import useIsMobile from '../../hooks/useIsMobile'
import useSwipeToClose from '../../hooks/useSwipeToClose'
import { formatDate, formatTime } from '../../utils/dateUtils'
import { strategyLabel } from '../../constants/strategies'
import TradeDetailModal from './TradeDetailModal'
import {
  formatPnl,
  formatPnlPercent,
  shortenWallet,
  type AffiliateLink,
  type BotStatistics,
  type BotStatus,
  type BotTrade,
} from './types'

interface Props {
  bot: BotStatus
  onClose: () => void
  t: (key: string) => string
}

export default function BotTradeHistoryModal({ bot, onClose, t }: Props) {
  const [stats, setStats] = useState<BotStatistics | null>(null)
  const [loading, setLoading] = useState(true)
  const [selectedTrade, setSelectedTrade] = useState<BotTrade | null>(null)
  const [expandedTradeId, setExpandedTradeId] = useState<number | null>(null)
  const [affiliateLink, setAffiliateLink] = useState<AffiliateLink | null>(null)
  const latestCardRef = useRef<HTMLDivElement>(null)
  const copyCardRef = useRef<HTMLDivElement>(null)
  const mobileShareRefs = useRef<Map<number, HTMLDivElement>>(new Map())
  const theme = useThemeStore((s) => s.theme)
  const isMobile = useIsMobile()
  const swipe = useSwipeToClose({ onClose, enabled: isMobile })

  useEffect(() => {
    const load = async () => {
      setLoading(true)
      try {
        const [statsRes, affRes] = await Promise.all([
          api.get(`/bots/${bot.bot_config_id}/statistics?days=365`),
          api.get('/affiliate-links'),
        ])
        setStats(statsRes.data)
        const links: AffiliateLink[] = affRes.data
        const match = links.find(l => l.exchange_type === bot.exchange_type)
        if (match) setAffiliateLink(match)
      } catch (err) {
        console.error('Failed to load bot trade history:', err)
        useToastStore.getState().addToast('error', t('common.error'))
      }
      setLoading(false)
    }
    load()
  }, [bot.bot_config_id, bot.exchange_type])

  const handleMobileDirectShare = async (trade: BotTrade) => {
    const ref = mobileShareRefs.current.get(trade.id)
    if (!ref) { setSelectedTrade(trade); return }
    try {
      const blob = await toBlob(ref, {
        pixelRatio: 2,
        backgroundColor: theme === 'light' ? '#f8fafc' : '#0b0f19',
      })
      if (!blob) { setSelectedTrade(trade); return }
      const file = new File([blob], 'trade.png', { type: 'image/png' })
      const pnlStr = trade.pnl_percent >= 0 ? `+${trade.pnl_percent.toFixed(2)}%` : `${trade.pnl_percent.toFixed(2)}%`
      if (navigator.share && navigator.canShare && navigator.canShare({ files: [file] })) {
        await navigator.share({
          title: `${trade.symbol} ${trade.side.toUpperCase()} ${pnlStr}`,
          text: affiliateLink?.affiliate_url || 'Edge Bots by Trading Department',
          files: [file],
        })
      } else {
        // Fallback: open modal
        setSelectedTrade(trade)
      }
    } catch (err) {
      if ((err as DOMException).name !== 'AbortError') {
        console.error('Failed to share image:', err)
        useToastStore.getState().addToast('error', t('common.error'))
      }
    }
  }

  const latestClosed = stats?.recent_trades.find(tr => tr.status === 'closed')

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <button
        type="button"
        aria-label={t('common.close')}
        onClick={onClose}
        className="absolute inset-0 w-full h-full bg-black/60 backdrop-blur-md border-0 appearance-none cursor-default"
      />
      <div
        ref={swipe.ref}
        style={swipe.style}
        role="dialog"
        aria-modal="true"
        aria-label={t('bots.tradeHistory')}
        onKeyDown={(e) => { if (e.key === 'Escape') onClose() }}
        className="relative bg-[#0b0f19] rounded-2xl max-w-5xl w-full mx-2 sm:mx-4 my-2 sm:my-3 max-h-[95vh] lg:max-h-[90vh] lg:my-6 flex flex-col border border-white/10 shadow-2xl overflow-hidden"
      >
        {isMobile && (
          <div className="flex justify-center pt-2 pb-1 lg:hidden">
            <div className="w-10 h-1 rounded-full bg-white/20" />
          </div>
        )}
        {/* Modal Header */}
        <div className="flex items-center justify-between px-6 py-3.5 border-b border-white/5 shrink-0">
          <div className="flex items-center gap-3">
            <div className="p-1.5 rounded-xl bg-white/5">
              <ExchangeIcon exchange={bot.exchange_type} size={20} />
            </div>
            <div>
              <h2 className="text-lg font-bold text-white">{bot.name}</h2>
              <div className="flex items-center gap-2 mt-0.5">
                <span className="text-xs text-gray-500">{strategyLabel(bot.strategy_type)}</span>
                {bot.strategy_type === 'copy_trading' ? (
                  <>
                    <span className="text-gray-700">·</span>
                    <span className="text-xs text-gray-400">
                      Source: <span className="font-mono">{shortenWallet(bot.copy_source_wallet)}</span>
                      {bot.copy_max_slots != null && <> · Slots: {bot.open_trades}/{bot.copy_max_slots}</>}
                      {bot.copy_budget_usdt != null && <> · Budget: ${bot.copy_budget_usdt}</>}
                    </span>
                  </>
                ) : bot.risk_profile && (
                  <>
                    <span className="text-gray-700">·</span>
                    <span className={`inline-flex items-center gap-0.5 text-xs ${
                      bot.risk_profile === 'aggressive' ? 'text-red-400' :
                      bot.risk_profile === 'conservative' ? 'text-blue-400' :
                      'text-gray-500'
                    }`}>
                      <Shield size={11} />
                      {t(`bots.builder.paramOption_risk_profile_${bot.risk_profile}`)}
                    </span>
                  </>
                )}
                <span className="text-gray-700">|</span>
                <span className={`text-xs font-medium ${bot.mode === 'demo' ? 'text-blue-400' : 'text-amber-400'}`}>
                  {bot.mode.toUpperCase()}
                </span>
              </div>
            </div>
          </div>
          <button
            onClick={onClose}
            className="hidden sm:block p-2 rounded-xl text-gray-400 hover:text-white hover:bg-white/5 transition-all"
            aria-label="Close"
          >
            <X size={22} />
          </button>
        </div>

        {/* Content - Scrollable */}
        <div className="flex-1 overflow-y-auto">
          {loading ? (
            <div className="flex items-center justify-center py-20">
              <RefreshCw size={24} className="animate-spin text-gray-500" />
            </div>
          ) : !stats || stats.recent_trades.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-20 text-gray-500">
              <Activity size={40} className="mb-3 opacity-30" />
              <p className="text-sm">{t('bots.noTrades')}</p>
            </div>
          ) : (
            <>
              {/* Summary Stats */}
              <div className="grid grid-cols-2 gap-2 p-4">
                <div className="glass-card rounded-xl p-3 text-center border border-white/5">
                  <div className="text-[10px] text-gray-400 uppercase tracking-wider mb-1">{t('bots.totalPnl')}</div>
                  <PnlCell
                    pnl={stats.summary.total_pnl}
                    fees={stats.summary.total_fees}
                    fundingPaid={stats.summary.total_funding ?? 0}
                    className={`text-lg font-bold ${stats.summary.total_pnl >= 0 ? 'text-profit' : 'text-loss'}`}
                  />
                </div>
                <div className="glass-card rounded-xl p-3 text-center border border-white/5">
                  <div className="text-[10px] text-gray-400 uppercase tracking-wider mb-1">{t('bots.winRate')}</div>
                  <div className={`text-lg font-bold ${stats.summary.win_rate >= 60 ? 'text-profit' : stats.summary.win_rate >= 40 ? 'text-yellow-400' : 'text-loss'}`}>
                    {stats.summary.win_rate}%
                  </div>
                  <div className="text-[10px] text-gray-500 mt-0.5">{stats.summary.wins}W / {stats.summary.losses}L</div>
                </div>
                <div className="glass-card rounded-xl p-3 text-center border border-white/5">
                  <div className="text-[10px] text-gray-400 uppercase tracking-wider mb-1 flex items-center justify-center gap-1">
                    <ArrowUpRight size={11} className="text-profit" /> {t('bots.bestTrade')}
                  </div>
                  <div className="text-lg font-bold text-profit">{formatPnl(stats.summary.best_trade)}</div>
                </div>
                <div className="glass-card rounded-xl p-3 text-center border border-white/5">
                  <div className="text-[10px] text-gray-400 uppercase tracking-wider mb-1 flex items-center justify-center gap-1">
                    <ArrowDownRight size={11} className="text-loss" /> {t('bots.worstTrade')}
                  </div>
                  <div className="text-lg font-bold text-loss">{formatPnl(stats.summary.worst_trade)}</div>
                </div>
              </div>

              {/* Latest Trade */}
              {latestClosed && (
                <div className="mx-3 mt-4 mb-2">
                  <div className="flex items-center mb-2">
                    <div className="text-xs text-gray-400 uppercase tracking-wider font-semibold">{t('bots.latestTrade')}</div>
                  </div>
                  {/* Visible card — uses MobileTradeCard style on mobile */}
                  <div ref={latestCardRef}>
                    <MobileTradeCard
                      trade={{
                        ...latestClosed,
                        bot_exchange: bot.exchange_type,
                        bot_name: bot.name,
                        entry_time: latestClosed.entry_time || '',
                        demo_mode: bot.mode === 'demo',
                      }}
                      extraDetails={[
                        ...(latestClosed.reason ? [{ label: t('bots.reasoning'), value: latestClosed.reason }] : []),
                      ]}
                    />
                  </div>

                  {/* Hidden compact card — used for share image export */}
                  <div className="absolute -left-[9999px] pointer-events-none" aria-hidden="true">
                    <div
                      ref={copyCardRef}
                      className="bg-[#0f1420] rounded-2xl p-5 border border-white/10 shadow-2xl" style={{ width: 420, minWidth: 420 }}
                    >
                      {/* Header: Exchange logo + Symbol */}
                      <div className="flex items-center gap-2 mb-1">
                        <ExchangeIcon exchange={bot.exchange_type} size={18} />
                        <span className="text-lg font-bold text-white">{latestClosed.symbol}</span>
                      </div>
                      {/* Perp | Side | Leverage | Date */}
                      <div className="flex items-center gap-2 text-sm text-gray-400 mb-4">
                          <span>Perp</span>
                          <span className="text-gray-600">|</span>
                          <span className={latestClosed.side === 'long' ? 'text-emerald-400 font-medium' : 'text-red-400 font-medium'}>
                            {latestClosed.side === 'long' ? '+ LONG' : '- SHORT'}
                          </span>
                          {latestClosed.leverage && (
                            <>
                              <span className="text-gray-600">|</span>
                              <span className="text-white font-medium">{latestClosed.leverage}x</span>
                            </>
                          )}
                          <span className="text-xs text-gray-500 shrink-0" style={{ marginLeft: 'auto' }}>{formatDate(latestClosed.entry_time)}</span>
                      </div>
                      {/* PnL - Hero */}
                      <div className="text-center py-5 mb-4">
                        <div className={`text-5xl font-bold tracking-tight ${latestClosed.pnl_percent >= 0 ? 'text-profit' : 'text-loss'}`}>
                          {formatPnlPercent(latestClosed.pnl_percent)}
                        </div>
                        <div className={`text-lg font-semibold mt-1 ${latestClosed.pnl >= 0 ? 'text-profit/70' : 'text-loss/70'}`}>
                          <PnlCell pnl={latestClosed.pnl} fees={latestClosed.fees ?? 0} fundingPaid={latestClosed.funding_paid ?? 0} status={latestClosed.status}
                            className={`text-lg font-semibold ${latestClosed.pnl >= 0 ? 'text-profit/70' : 'text-loss/70'}`} />
                        </div>
                      </div>
                      {/* Entry / Exit */}
                      <div className="grid grid-cols-2 gap-4 max-w-xs mx-auto mb-4">
                        <div className="text-center">
                          <div className="text-xs text-gray-400 mb-1">{t('bots.entryPrice')}</div>
                          <div className="text-white font-semibold text-lg">${latestClosed.entry_price.toLocaleString()}</div>
                        </div>
                        <div className="text-center">
                          <div className="text-xs text-gray-400 mb-1">{t('bots.exitPrice')}</div>
                          <div className="text-white font-semibold text-lg">{latestClosed.exit_price ? `$${latestClosed.exit_price.toLocaleString()}` : '--'}</div>
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
              )}

              {/* Trade History Table */}
              <div className="px-6 pt-3 pb-2">
                <div className="text-xs text-gray-400 uppercase tracking-wider font-semibold">{t('bots.tradeHistory')}</div>
              </div>
              {isMobile ? (
                <div className="px-3 pb-6 space-y-1.5">
                  {stats.recent_trades.map(trade => (
                    <MobileTradeCard key={trade.id} trade={{ ...trade, bot_exchange: bot.exchange_type, entry_time: trade.entry_time || '' }} onShare={() => handleMobileDirectShare(trade)} />
                  ))}
                  {/* Hidden capture divs for mobile direct share */}
                  <div className="absolute -left-[9999px] pointer-events-none" aria-hidden="true">
                    {stats.recent_trades.filter(tr => tr.status === 'closed').map((trade) => (
                      <div
                        key={trade.id}
                        ref={(el) => { if (el) mobileShareRefs.current.set(trade.id, el); else mobileShareRefs.current.delete(trade.id) }}
                        className="bg-[#0f1420] rounded-2xl p-5 border border-white/10 shadow-2xl" style={{ width: 420, minWidth: 420 }}
                      >
                        <div className="flex items-center gap-2 mb-1">
                          <ExchangeIcon exchange={bot.exchange_type} size={18} />
                          <span className="text-lg font-bold text-white">{trade.symbol}</span>
                        </div>
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
                            <span className="text-xs text-gray-500 shrink-0" style={{ marginLeft: 'auto' }}>{formatDate(trade.entry_time)}</span>
                        </div>
                        <div className="text-center py-5 mb-4">
                          <div className={`text-5xl font-bold tracking-tight ${trade.pnl_percent >= 0 ? 'text-profit' : 'text-loss'}`}>
                            {formatPnlPercent(trade.pnl_percent)}
                          </div>
                          <div className={`text-lg font-semibold mt-1 ${trade.pnl >= 0 ? 'text-profit/70' : 'text-loss/70'}`}>
                            <PnlCell pnl={trade.pnl} fees={trade.fees ?? 0} fundingPaid={trade.funding_paid ?? 0} status={trade.status}
                              className={`text-lg font-semibold ${trade.pnl >= 0 ? 'text-profit/70' : 'text-loss/70'}`} />
                          </div>
                        </div>
                        <div className="grid grid-cols-2 gap-4 max-w-xs mx-auto mb-4">
                          <div className="text-center">
                            <div className="text-xs text-gray-400 mb-1">{t('bots.entryPrice')}</div>
                            <div className="text-white font-semibold text-lg">${trade.entry_price.toLocaleString()}</div>
                          </div>
                          <div className="text-center">
                            <div className="text-xs text-gray-400 mb-1">{t('bots.exitPrice')}</div>
                            <div className="text-white font-semibold text-lg">{trade.exit_price ? `$${trade.exit_price.toLocaleString()}` : '--'}</div>
                          </div>
                        </div>
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
                    ))}
                  </div>
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="table-premium w-full">
                    <thead>
                      <tr>
                        <th className="text-left">{t('trades.date')}</th>
                        <th className="text-center hidden lg:table-cell">{t('trades.exchange')}</th>
                        <th className="text-left">{t('trades.symbol')}</th>
                        <th className="text-center">{t('trades.side')}</th>
                        <th className="text-right hidden xl:table-cell">{t('trades.entryPrice')}</th>
                        <th className="text-right hidden xl:table-cell">{t('trades.exitPrice')}</th>
                        <th className="text-right">{t('trades.pnl')}</th>
                        <th className="text-center hidden 2xl:table-cell">{t('trades.mode')}</th>
                        <th className="text-center">{t('trades.status')}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {stats.recent_trades.map((trade) => (
                        <Fragment key={trade.id}>
                          <tr
                            tabIndex={0}
                            aria-expanded={expandedTradeId === trade.id}
                            onClick={() => setExpandedTradeId(expandedTradeId === trade.id ? null : trade.id)}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter' || e.key === ' ') {
                                e.preventDefault()
                                setExpandedTradeId(expandedTradeId === trade.id ? null : trade.id)
                              }
                            }}
                            className="cursor-pointer"
                          >
                            <td className="text-gray-300">
                              <span className="inline-flex items-center">
                                <ChevronRight size={14} className={`expand-chevron ${expandedTradeId === trade.id ? 'open' : ''}`} />
                                <span title={formatTime(trade.entry_time)}>{formatDate(trade.entry_time)}</span>
                              </span>
                            </td>
                            <td className="text-center hidden lg:table-cell">
                              <span className="inline-flex justify-center">
                                <ExchangeIcon exchange={bot.exchange_type} size={18} />
                              </span>
                            </td>
                            <td className="text-white font-medium">{trade.symbol}</td>
                            <td className="text-center">
                              <span className={trade.side === 'long' ? 'text-profit' : 'text-loss'}>
                                {trade.side === 'long' ? '+' : '-'} {trade.side.toUpperCase()}
                              </span>
                            </td>
                            <td className="text-right text-gray-300 hidden xl:table-cell">${trade.entry_price.toLocaleString()}</td>
                            <td className="text-right text-gray-300 hidden xl:table-cell">
                              {trade.exit_price ? `$${trade.exit_price.toLocaleString()}` : '--'}
                            </td>
                            <td className="text-right">
                              <PnlCell
                                pnl={trade.pnl}
                                fees={trade.fees ?? 0}
                                fundingPaid={trade.funding_paid ?? 0}
                                status={trade.status}
                                className={trade.pnl >= 0 ? 'pnl-positive' : 'pnl-negative'}
                              />
                            </td>
                            <td className="text-center hidden 2xl:table-cell">
                              <span className={trade.demo_mode ? 'badge-demo' : 'badge-live'}>
                                {trade.demo_mode ? t('common.demo') : t('common.live')}
                              </span>
                            </td>
                            <td className="text-center">
                              <span className={
                                trade.status === 'open' ? 'badge-open' :
                                trade.status === 'closed' ? 'badge-neutral' :
                                'badge-demo'
                              }>
                                {t(`trades.${trade.status}`)}
                              </span>
                            </td>
                          </tr>
                          {expandedTradeId === trade.id && (
                            <tr className="table-expand-row">
                              <td colSpan={9} className="!p-0 !border-b-0">
                                <dl className="table-expand-content">
                                  <div className="xl:hidden">
                                    <dt>{t('trades.entryPrice')}</dt>
                                    <dd>${trade.entry_price.toLocaleString()}</dd>
                                  </div>
                                  <div className="xl:hidden">
                                    <dt>{t('trades.exitPrice')}</dt>
                                    <dd>{trade.exit_price ? `$${trade.exit_price.toLocaleString()}` : '--'}</dd>
                                  </div>
                                  <div>
                                    <dt>{t('trades.size')}</dt>
                                    <dd><SizeValue size={trade.size} price={trade.entry_price} symbol={trade.symbol} /></dd>
                                  </div>
                                  <div>
                                    <dt>{t('trades.pnl')} %</dt>
                                    <dd className={trade.pnl_percent >= 0 ? 'text-profit' : 'text-loss'}>
                                      {trade.pnl_percent >= 0 ? '+' : ''}{trade.pnl_percent.toFixed(2)}%
                                    </dd>
                                  </div>
                                  <div className="2xl:hidden">
                                    <dt>{t('trades.mode')}</dt>
                                    <dd className="flex items-center gap-3">
                                      <span>{trade.demo_mode ? t('common.demo') : t('common.live')}</span>
                                      <button
                                        onClick={() => setSelectedTrade({ ...trade, exchange: bot.exchange_type })}
                                        className="p-1.5 rounded-lg text-gray-400 hover:text-white bg-white/5 hover:bg-white/10 border border-white/5 transition-all"
                                        title={t('bots.shareImage')}
                                        aria-label="Share trade"
                                      >
                                        <Share2 size={13} />
                                      </button>
                                    </dd>
                                  </div>
                                  {trade.exit_time && (
                                    <div>
                                      <dt>{t('trades.exitTime')}</dt>
                                      <dd>{formatDate(trade.exit_time)} {formatTime(trade.exit_time)}</dd>
                                    </div>
                                  )}
                                  {trade.exit_reason && (
                                    <div>
                                      <dt>{t('trades.exitReason')}</dt>
                                      <dd><ExitReasonBadge reason={trade.exit_reason} /></dd>
                                    </div>
                                  )}
                                  {trade.fees > 0 && (
                                    <div>
                                      <dt>{t('trades.fees')}</dt>
                                      <dd>${trade.fees.toFixed(2)}</dd>
                                    </div>
                                  )}
                                  {trade.leverage && (
                                    <div>
                                      <dt>{t('trades.leverage')}</dt>
                                      <dd>{trade.leverage}x</dd>
                                    </div>
                                  )}
                                </dl>
                              </td>
                            </tr>
                          )}
                        </Fragment>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {/* Trade Detail Modal (nested, higher z-index) */}
      {selectedTrade && (
        <TradeDetailModal trade={selectedTrade} onClose={() => setSelectedTrade(null)} t={t} affiliateLink={affiliateLink} />
      )}
    </div>
  )
}
