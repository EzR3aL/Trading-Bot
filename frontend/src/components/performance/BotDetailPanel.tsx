import { Fragment, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Bar,
  CartesianGrid,
  Cell,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { ArrowDownRight, ArrowUpRight, ChevronRight, Eye, EyeOff, Share2 } from 'lucide-react'
import PnlCell from '../ui/PnlCell'
import { ExchangeIcon } from '../ui/ExchangeLogo'
import ExitReasonBadge from '../ui/ExitReasonBadge'
import MobileTradeCard from '../ui/MobileTradeCard'
import SizeValue from '../ui/SizeValue'
import { strategyLabel } from '../../constants/strategies'
import { formatChartCurrency, formatDate, formatTime } from '../../utils/dateUtils'
import BotPnlTooltip from './BotPnlTooltip'
import StatCard from './StatCard'
import {
  CUMULATIVE_COLOR,
  FEES_COLOR,
  FUNDING_COLOR,
  PNL_NEG,
  PNL_POS,
  formatPnl,
  formatPnlPercent,
  type AffiliateLink,
  type BotCompareData,
  type BotDetailRecentTrade,
  type BotDetailStats,
} from './types'

interface ChartPoint {
  date: string
  dailyPnl: number
  fees: number
  funding: number
  cumulativePnl: number
}

interface Props {
  botDetail: BotDetailStats
  selectedBotData: BotCompareData | null
  affiliateLink: AffiliateLink | null
  botChartData: ChartPoint[]
  isMobile: boolean
  chartGridColor: string
  chartTickColor: string
  refColor: string
  sharingTrade: BotDetailRecentTrade | null
  shareResolveRef: React.MutableRefObject<((el: HTMLDivElement | null) => void) | null>
  onSelectTrade: (trade: BotDetailRecentTrade) => void
  onMobileDirectShare: (trade: BotDetailRecentTrade) => void
}

/**
 * Right-hand "details" panel rendered when a bot is selected on BotPerformance:
 * summary stat tiles, latest-trade card, daily PnL chart, and the recent-trades
 * table (desktop) or list of MobileTradeCards (mobile) with lazy-mounted share.
 */
export default function BotDetailPanel({
  botDetail,
  selectedBotData,
  affiliateLink,
  botChartData,
  isMobile,
  chartGridColor,
  chartTickColor,
  refColor,
  sharingTrade,
  shareResolveRef,
  onSelectTrade,
  onMobileDirectShare,
}: Props) {
  const { t } = useTranslation()
  const [expandedTradeId, setExpandedTradeId] = useState<number | null>(null)
  const [showCosts, setShowCosts] = useState(true)

  const botExchange = selectedBotData?.exchange_type || ''
  const latestClosed = botDetail.recent_trades.find(tr => tr.status === 'closed')

  return (
    <div className="glass-card rounded-xl p-5 slide-in-panel">
      <h2 className="text-white font-semibold mb-4">
        {botDetail.bot_name} -- {t('performance.details')}
        {selectedBotData?.strategy_type && (
          <span className="ml-2 text-sm font-normal text-gray-400">{strategyLabel(selectedBotData.strategy_type)}</span>
        )}
      </h2>

      {/* Summary Cards (centered) */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-5">
        <div className="bg-white/5 rounded-xl p-3 border border-white/5 text-center">
          <div className="text-[10px] text-gray-400 mb-1 uppercase tracking-wider font-medium">{t('performance.totalPnl')}</div>
          <div className={`text-lg font-bold flex items-center justify-center gap-1 ${botDetail.summary.total_pnl >= 0 ? 'text-profit' : 'text-loss'}`}>
            <PnlCell
              pnl={botDetail.summary.total_pnl}
              fees={botDetail.summary.total_fees ?? 0}
              fundingPaid={botDetail.summary.total_funding ?? 0}
              className={`text-lg font-bold ${botDetail.summary.total_pnl >= 0 ? 'text-profit' : 'text-loss'}`}
            />
            {botDetail.summary.total_pnl >= 0
              ? <ArrowUpRight size={16} className="text-profit" />
              : <ArrowDownRight size={16} className="text-loss" />
            }
          </div>
        </div>
        <StatCard
          label={t('performance.winRate')}
          value={`${botDetail.summary.win_rate}%`}
          color={botDetail.summary.win_rate >= 60 ? 'text-profit' : botDetail.summary.win_rate >= 40 ? 'text-yellow-400' : 'text-loss'}
        />
        <StatCard
          label={t('performance.bestTrade')}
          value={formatPnl(botDetail.summary.best_trade)}
          color="text-profit"
          isPositive={true}
        />
        <StatCard
          label={t('performance.worstTrade')}
          value={formatPnl(botDetail.summary.worst_trade)}
          color="text-loss"
          isPositive={false}
        />
      </div>

      {/* Latest Trade Card */}
      {latestClosed && (
        <div className="mb-5">
          <div className="flex items-center mb-2">
            <div className="text-xs text-gray-400 uppercase tracking-wider font-semibold">{t('bots.latestTrade')}</div>
          </div>
          <div
            role="button"
            tabIndex={0}
            aria-label={t('bots.latestTrade')}
            className="bg-white/[0.02] rounded-xl p-4 border border-white/5 cursor-pointer hover:border-white/10 transition-all"
            onClick={() => onSelectTrade(latestClosed)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault()
                onSelectTrade(latestClosed)
              }
            }}
          >
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-3">
                <span className="text-white font-bold text-lg">{latestClosed.symbol}</span>
                <span className={`px-2 py-0.5 rounded-lg text-sm font-bold ${
                  latestClosed.side === 'long' ? 'bg-emerald-500/15 text-profit border border-emerald-500/20' : 'bg-red-500/15 text-loss border border-red-500/20'
                }`}>
                  {latestClosed.side === 'long' ? '+ LONG' : '- SHORT'}
                </span>
                {latestClosed.leverage && (
                  <span className="text-sm font-semibold text-white bg-white/10 px-2 py-0.5 rounded-lg">{latestClosed.leverage}x</span>
                )}
              </div>
              <span className="text-xs text-gray-500" title={formatTime(latestClosed.entry_time)}>
                {formatDate(latestClosed.entry_time)}
              </span>
            </div>
            {/* Mobile: centered PnL + entry/exit row */}
            <div className="sm:hidden">
              <div className="text-center my-4">
                <div className={`text-4xl font-bold tracking-tight ${latestClosed.pnl_percent >= 0 ? 'text-profit' : 'text-loss'}`}>
                  {formatPnlPercent(latestClosed.pnl_percent)}
                </div>
                <PnlCell pnl={latestClosed.pnl} fees={latestClosed.fees ?? 0} fundingPaid={latestClosed.funding_paid ?? 0} status={latestClosed.status}
                  className={`text-lg font-semibold ${latestClosed.pnl >= 0 ? 'text-profit/70' : 'text-loss/70'}`} />
              </div>
              <div className="grid grid-cols-2 gap-4 max-w-xs mx-auto">
                <div className="text-center">
                  <div className="text-xs text-gray-400 mb-1">{t('bots.entryPrice')}</div>
                  <div className="text-white font-semibold text-lg">${latestClosed.entry_price.toLocaleString()}</div>
                </div>
                <div className="text-center">
                  <div className="text-xs text-gray-400 mb-1">{t('bots.exitPrice')}</div>
                  <div className="text-white font-semibold text-lg">{latestClosed.exit_price ? `$${latestClosed.exit_price.toLocaleString()}` : '--'}</div>
                </div>
              </div>
            </div>
            {/* Desktop: horizontal grid */}
            <div className="hidden sm:grid grid-cols-4 gap-4">
              <div>
                <div className="text-xs text-gray-400 uppercase tracking-wider mb-0.5">{t('bots.result')}</div>
                <div className={`text-2xl font-bold tracking-tight ${latestClosed.pnl_percent >= 0 ? 'text-profit' : 'text-loss'}`}>
                  {formatPnlPercent(latestClosed.pnl_percent)}
                </div>
                <PnlCell pnl={latestClosed.pnl} fees={latestClosed.fees ?? 0} fundingPaid={latestClosed.funding_paid ?? 0} status={latestClosed.status}
                  className={`text-sm font-medium ${latestClosed.pnl >= 0 ? 'text-profit/60' : 'text-loss/60'}`} />
              </div>
              <div>
                <div className="text-xs text-gray-400 uppercase tracking-wider mb-0.5">{t('bots.entryPrice')}</div>
                <div className="text-lg font-bold text-white">${latestClosed.entry_price.toLocaleString()}</div>
              </div>
              <div>
                <div className="text-xs text-gray-400 uppercase tracking-wider mb-0.5">{t('bots.exitPrice')}</div>
                <div className="text-lg font-bold text-white">
                  {latestClosed.exit_price ? `$${latestClosed.exit_price.toLocaleString()}` : '--'}
                </div>
              </div>
            </div>
            <div className="mt-3 pt-2 border-t border-white/5">
              <div className="text-xs text-gray-500">Edge Bots by Trading Department</div>
              {affiliateLink && (
                <div className="flex items-center justify-between mt-0.5">
                  <span className="text-xs text-gray-500">{affiliateLink.label || t('bots.affiliateLink')}</span>
                  <span className="text-xs text-primary-400 font-medium">{affiliateLink.affiliate_url}</span>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Bot PnL Chart (stacked bars + cumulative line) */}
      {botChartData.length > 0 && (
        <div className="mb-5 relative">
          <button
            onClick={() => setShowCosts(!showCosts)}
            className={`absolute -top-1 right-0 z-10 flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium transition-all duration-200 border ${
              showCosts
                ? 'bg-white/5 border-white/10 text-gray-300 hover:bg-white/10'
                : 'bg-white/[0.02] border-white/5 text-gray-500 hover:text-gray-400'
            }`}
          >
            {showCosts ? <Eye size={13} /> : <EyeOff size={13} />}
            {t('dashboard.fees')} & {t('dashboard.funding')}
          </button>
          <div className="pt-8">
            <ResponsiveContainer width="100%" height={250}>
              <ComposedChart data={botChartData} margin={{ top: 5, right: 10, left: 10, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={chartGridColor} vertical={false} />
                <XAxis dataKey="date" tick={{ fill: chartTickColor, fontSize: 10 }} tickLine={false} />
                <YAxis width={45} tick={{ fill: chartTickColor, fontSize: 10 }} tickLine={false} tickFormatter={formatChartCurrency} />
                <Tooltip content={<BotPnlTooltip t={t} />} />
                <ReferenceLine y={0} stroke={refColor} strokeDasharray="3 3" />
                <Bar dataKey="dailyPnl" name={t('dashboard.dailyPnl')} stackId="pnl" maxBarSize={40}>
                  {botChartData.map((entry, index) => (
                    <Cell key={index} fill={entry.dailyPnl >= 0 ? PNL_POS : PNL_NEG} fillOpacity={0.75} />
                  ))}
                </Bar>
                {showCosts && (
                  <Bar dataKey="fees" name={t('dashboard.fees')} stackId="pnl" fill={FEES_COLOR} fillOpacity={0.8} maxBarSize={40} />
                )}
                {showCosts && (
                  <Bar dataKey="funding" name={t('dashboard.funding')} stackId="pnl" fill={FUNDING_COLOR} fillOpacity={0.8} maxBarSize={40} radius={[3, 3, 0, 0]} />
                )}
                <Line
                  type="monotone"
                  dataKey="cumulativePnl"
                  name={t('dashboard.cumulativePnl')}
                  stroke={CUMULATIVE_COLOR}
                  strokeWidth={2}
                  dot={false}
                  activeDot={{ r: 4, fill: CUMULATIVE_COLOR, stroke: '#fff', strokeWidth: 1 }}
                />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* Recent Trades */}
      <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">{t('performance.recentTrades')}</h3>
      {isMobile ? (
        <div className="space-y-2">
          {botDetail.recent_trades.map((trade) => (
            <MobileTradeCard
              key={trade.id}
              trade={{
                ...trade,
                entry_time: trade.entry_time || '',
                pnl_percent: trade.pnl_percent,
                fees: trade.fees,
                funding_paid: trade.funding_paid,
                bot_exchange: botExchange,
                exit_reason: trade.exit_reason,
              }}
              extraDetails={[
                ...(trade.reason ? [{ label: t('bots.reasoning'), value: trade.reason }] : []),
              ]}
              onShare={() => onMobileDirectShare(trade)}
            />
          ))}
          {/*
            Hidden capture div for mobile direct share.
            Only mounts while a share is in-flight (sharingTrade !== null)
            and only for the single trade being shared. The callback
            ref below fires after React commits the node, which lets
            handleMobileDirectShare await the mount before calling
            toBlob — otherwise the first click would capture nothing.
          */}
          {sharingTrade && sharingTrade.status === 'closed' && (
            <div className="absolute -left-[9999px] pointer-events-none" aria-hidden="true" data-testid="mobile-share-capture">
              <div
                ref={(el) => {
                  const resolve = shareResolveRef.current
                  if (el && resolve) {
                    shareResolveRef.current = null
                    resolve(el)
                  }
                }}
                className="bg-[#0f1420] rounded-2xl p-5 border border-white/10 shadow-2xl" style={{ width: 420, minWidth: 420 }}
              >
                <div className="flex items-center gap-2 mb-1">
                  <ExchangeIcon exchange={botExchange} size={18} />
                  <span className="text-lg font-bold text-white">{sharingTrade.symbol}</span>
                </div>
                <div className="flex items-center gap-2 text-sm text-gray-400 mb-4">
                    <span>Perp</span>
                    <span className="text-gray-600">|</span>
                    <span className={sharingTrade.side === 'long' ? 'text-emerald-400 font-medium' : 'text-red-400 font-medium'}>
                      {sharingTrade.side === 'long' ? '+ LONG' : '- SHORT'}
                    </span>
                    {sharingTrade.leverage && (
                      <>
                        <span className="text-gray-600">|</span>
                        <span className="text-white font-medium">{sharingTrade.leverage}x</span>
                      </>
                    )}
                    <span className="text-xs text-gray-500 shrink-0" style={{ marginLeft: 'auto' }}>{formatDate(sharingTrade.entry_time)}</span>
                </div>
                <div className="text-center py-5 mb-4">
                  <div className={`text-5xl font-bold tracking-tight ${sharingTrade.pnl_percent >= 0 ? 'text-profit' : 'text-loss'}`}>
                    {formatPnlPercent(sharingTrade.pnl_percent)}
                  </div>
                  <div className={`text-lg font-semibold mt-1 ${sharingTrade.pnl >= 0 ? 'text-profit/70' : 'text-loss/70'}`}>
                    <PnlCell pnl={sharingTrade.pnl} fees={sharingTrade.fees ?? 0} fundingPaid={sharingTrade.funding_paid ?? 0} status={sharingTrade.status}
                      className={`text-lg font-semibold ${sharingTrade.pnl >= 0 ? 'text-profit/70' : 'text-loss/70'}`} />
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-4 max-w-xs mx-auto mb-4">
                  <div className="text-center">
                    <div className="text-xs text-gray-400 mb-1">{t('bots.entryPrice')}</div>
                    <div className="text-white font-semibold text-lg">${sharingTrade.entry_price.toLocaleString()}</div>
                  </div>
                  <div className="text-center">
                    <div className="text-xs text-gray-400 mb-1">{t('bots.exitPrice')}</div>
                    <div className="text-white font-semibold text-lg">{sharingTrade.exit_price ? `$${sharingTrade.exit_price.toLocaleString()}` : '--'}</div>
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
            </div>
          )}
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-white/5">
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
              {botDetail.recent_trades.map((trade) => (
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
                      <ExchangeIcon exchange={botExchange} size={18} />
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
                      className={trade.pnl && trade.pnl >= 0 ? 'pnl-positive' : 'pnl-negative'}
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
                          <dd><SizeValue size={trade.size ?? 0} price={trade.entry_price} symbol={trade.symbol} /></dd>
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
                              onClick={() => onSelectTrade(trade)}
                              className="p-1.5 rounded-lg text-gray-400 hover:text-white bg-white/5 hover:bg-white/10 border border-white/5 transition-all"
                              title={t('bots.shareImage')}
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
                        {trade.reason && (
                          <div className="col-span-2">
                            <dt>{t('bots.reasoning')}</dt>
                            <dd className="text-gray-400 text-xs">{trade.reason}</dd>
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
    </div>
  )
}
