import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { DollarSign, RefreshCw, AlertTriangle, CheckCircle2, XCircle, Clock } from 'lucide-react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Legend,
} from 'recharts'
import api from '../api/client'
import { getApiErrorMessage } from '../utils/api-error'
import { useToastStore } from '../stores/toastStore'
import { ExchangeIcon } from '../components/ui/ExchangeLogo'

interface RevenueSummary {
  today: number
  last_7d: number
  last_30d: number
  total: number
}

interface ExchangeBreakdown {
  exchange: string
  type: string
  total: number
  count: number
}

interface DailyRevenue {
  date: string
  total: number
  by_exchange: Record<string, number>
}

interface SignupData {
  total: number
  by_exchange: Record<string, number>
}

interface SyncStatus {
  status: string | null  // ok | error | unsupported | not_configured | null
  last_synced_at: string | null
  error: string | null
}

interface RevenueResponse {
  summary: RevenueSummary
  by_exchange: ExchangeBreakdown[]
  daily: DailyRevenue[]
  signups: SignupData
  sync_status: Record<string, SyncStatus>
}

const PERIOD_KEYS = [
  { value: '7d', labelKey: 'admin.period7d' },
  { value: '30d', labelKey: 'admin.period30d' },
  { value: '90d', labelKey: 'admin.period90d' },
  { value: '1y', labelKey: 'admin.period1y' },
]

const EXCHANGE_COLORS: Record<string, string> = {
  hyperliquid: '#00D1FF',
  bitget: '#00C49F',
  weex: '#FFB800',
  bingx: '#2962FF',
  bitunix: '#FF6B35',
}

const EXCHANGE_LABELS: Record<string, string> = {
  hyperliquid: 'Hyperliquid',
  bitget: 'Bitget',
  weex: 'Weex',
  bingx: 'BingX',
  bitunix: 'Bitunix',
}

const ALL_EXCHANGES = ['hyperliquid', 'bitget', 'weex', 'bingx', 'bitunix']

function formatCurrency(value: number): string {
  return new Intl.NumberFormat('de-DE', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value)
}

function formatChartDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit' })
}

function getExchangeColor(exchange: string): string {
  return EXCHANGE_COLORS[exchange.toLowerCase()] || '#6B7280'
}

function formatRelative(iso: string | null, t: (key: string) => string): string {
  if (!iso) return t('admin.neverSynced')
  const diffMs = Date.now() - new Date(iso).getTime()
  const m = Math.round(diffMs / 60_000)
  if (m < 1) return t('admin.justNow')
  if (m < 60) return `vor ${m}m`
  const h = Math.round(m / 60)
  if (h < 24) return `vor ${h}h`
  return `vor ${Math.round(h / 24)}d`
}

function StatusBadge({ status, exchange, t }: { status: SyncStatus | undefined; exchange: string; t: (key: string) => string }) {
  if (exchange === 'bitunix' || status?.status === 'unsupported') {
    return (
      <span className="inline-flex items-center gap-1 text-[10px] text-amber-400" title={status?.error || ''}>
        <AlertTriangle size={11} /> {t('admin.apiNotAvailable')}
      </span>
    )
  }
  if (!status || status.status === null) {
    return (
      <span className="inline-flex items-center gap-1 text-[10px] text-gray-500">
        <Clock size={11} /> {t('admin.noSyncYet')}
      </span>
    )
  }
  if (status.status === 'not_configured') {
    return (
      <span className="inline-flex items-center gap-1 text-[10px] text-gray-500" title="Credentials in .env nicht hinterlegt">
        <Clock size={11} /> {t('admin.notConfigured')}
      </span>
    )
  }
  if (status.status === 'ok') {
    return (
      <span className="inline-flex items-center gap-1 text-[10px] text-emerald-400">
        <CheckCircle2 size={11} /> {formatRelative(status.last_synced_at, t)}
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1 text-[10px] text-red-400" title={status.error || ''}>
      <XCircle size={11} /> {t('admin.error')}
    </span>
  )
}

function RevenueTimeChart({ data, t }: { data: DailyRevenue[]; t: (key: string) => string }) {
  if (data.length === 0) {
    return <div className="flex items-center justify-center h-[200px] text-gray-500 text-sm">{t('admin.noChartData')}</div>
  }
  const chartData = data.map((d) => ({
    date: formatChartDate(d.date),
    ...Object.fromEntries(ALL_EXCHANGES.map((ex) => [ex, d.by_exchange[ex] ?? 0])),
    total: d.total,
  }))
  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart data={chartData} margin={{ top: 5, right: 10, left: 10, bottom: 5 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
        <XAxis dataKey="date" tick={{ fill: '#9ca3af', fontSize: 10 }} tickLine={false} />
        <YAxis width={50} tick={{ fill: '#9ca3af', fontSize: 10 }} tickLine={false} tickFormatter={(v) => `$${v}`} />
        <Tooltip
          contentStyle={{ backgroundColor: '#1f2937', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px', fontSize: '12px' }}
          labelStyle={{ color: '#9ca3af' }}
          formatter={(value: number, name: string) => [formatCurrency(value), EXCHANGE_LABELS[name] || name]}
        />
        <Legend wrapperStyle={{ fontSize: '11px' }} formatter={(value) => <span className="text-gray-400">{EXCHANGE_LABELS[value] || value}</span>} />
        {ALL_EXCHANGES.map((ex) => (
          <Bar key={ex} dataKey={ex} name={ex} stackId="revenue" fill={EXCHANGE_COLORS[ex]} radius={ex === ALL_EXCHANGES[ALL_EXCHANGES.length - 1] ? [2, 2, 0, 0] : [0, 0, 0, 0]} />
        ))}
      </BarChart>
    </ResponsiveContainer>
  )
}

export default function AdminRevenue() {
  const { t } = useTranslation()
  const addToast = useToastStore((s) => s.addToast)
  const [period, setPeriod] = useState('30d')
  const [data, setData] = useState<RevenueResponse | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isSyncing, setIsSyncing] = useState(false)

  const loadRevenue = useCallback(async () => {
    setIsLoading(true)
    try {
      const res = await api.get<RevenueResponse>('/admin/revenue', { params: { period } })
      setData(res.data)
    } catch (err) {
      addToast('error', getApiErrorMessage(err, t('admin.loadError')))
    } finally {
      setIsLoading(false)
    }
  }, [period, addToast])

  useEffect(() => {
    loadRevenue()
  }, [loadRevenue])

  const handleSync = async () => {
    setIsSyncing(true)
    try {
      const res = await api.post<{ summary: Record<string, { status: string }> }>('/admin/revenue/sync')
      const failed = Object.entries(res.data.summary || {}).filter(([, v]) => v.status === 'error')
      if (failed.length === 0) {
        addToast('success', t('admin.syncDone'))
      } else {
        addToast('error', `${t('admin.syncWithErrors')}: ${failed.map(([k]) => k).join(', ')}`)
      }
      await loadRevenue()
    } catch (err) {
      addToast('error', getApiErrorMessage(err, t('admin.syncFailed')))
    } finally {
      setIsSyncing(false)
    }
  }

  const summary = data?.summary
  const exchangeData = ALL_EXCHANGES.map((ex) => {
    const found = data?.by_exchange?.filter((e) => e.exchange.toLowerCase() === ex)
    const total = found?.reduce((sum, e) => sum + e.total, 0) ?? 0
    const count = found?.reduce((sum, e) => sum + e.count, 0) ?? 0
    const types = found?.map((e) => e.type).join(', ') || '-'
    return { exchange: ex, total, count, types }
  })

  return (
    <div>
      <div className="flex items-center justify-between mb-5">
        <div className="flex items-center gap-2">
          <DollarSign size={20} className="text-emerald-400" />
          <h1 className="text-2xl font-bold text-white">{t('admin.revenueTitle')}</h1>
        </div>
        <button
          onClick={handleSync}
          disabled={isSyncing}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-primary-600 hover:bg-primary-700 text-white transition-colors disabled:opacity-60"
        >
          <RefreshCw size={14} className={isSyncing ? 'animate-spin' : ''} />
          {t('admin.syncNow')}
        </button>
      </div>

      <div className="flex gap-1 mb-5 bg-gray-900 p-1 rounded-lg w-fit">
        {PERIOD_KEYS.map((p) => (
          <button
            key={p.value}
            onClick={() => setPeriod(p.value)}
            className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-all ${
              period === p.value
                ? 'bg-primary-500/20 text-primary-400 ring-1 ring-primary-500/30'
                : 'text-gray-500 hover:text-white hover:bg-white/5'
            }`}
          >
            {t(p.labelKey)}
          </button>
        ))}
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-12">
          <div className="w-6 h-6 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin" />
        </div>
      ) : data ? (
        <div className="space-y-6">
          {summary && (
            <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
              {[
                { label: t('admin.revenueToday'), value: summary.today },
                { label: t('admin.revenue7d'), value: summary.last_7d },
                { label: t('admin.revenue30d'), value: summary.last_30d },
                { label: t('admin.revenueTotal'), value: summary.total },
              ].map((kpi) => (
                <div key={kpi.label} className="border border-white/[0.08] bg-white/[0.02] rounded-xl p-4 hover:bg-white/[0.04] transition-colors">
                  <p className="text-[10px] text-gray-400 uppercase tracking-wider mb-1">{kpi.label}</p>
                  <p className="text-xl font-bold text-emerald-400 tabular-nums">{formatCurrency(kpi.value)}</p>
                </div>
              ))}
              <div className="border border-white/[0.08] bg-white/[0.02] rounded-xl p-4 hover:bg-white/[0.04] transition-colors">
                <p className="text-[10px] text-gray-400 uppercase tracking-wider mb-1">{t('admin.affiliateSignups')}</p>
                <p className="text-xl font-bold text-primary-400 tabular-nums">{data?.signups?.total ?? 0}</p>
              </div>
            </div>
          )}

          {data.daily.length > 0 && (
            <div>
              <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wider mb-3">{t('admin.timeline')}</h3>
              <div className="border border-white/[0.08] bg-white/[0.02] rounded-xl p-4">
                <RevenueTimeChart data={data.daily} t={t} />
              </div>
            </div>
          )}

          <div>
            <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wider mb-3">{t('admin.byExchange')}</h3>
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
              {exchangeData.map((ex) => {
                const color = getExchangeColor(ex.exchange)
                const status = data.sync_status?.[ex.exchange]
                const hasData = ex.total > 0
                const isUnsupported = ex.exchange === 'bitunix' || status?.status === 'unsupported'
                return (
                  <div
                    key={ex.exchange}
                    className={`border rounded-xl p-4 relative overflow-hidden transition-colors ${
                      hasData
                        ? 'border-white/[0.08] bg-white/[0.02] hover:bg-white/[0.04]'
                        : isUnsupported
                          ? 'border-amber-500/20 bg-amber-500/[0.03]'
                          : 'border-white/[0.05] bg-white/[0.01] opacity-70'
                    }`}
                  >
                    <div className="absolute top-0 left-0 w-full h-0.5" style={{ backgroundColor: color, opacity: hasData ? 1 : 0.3 }} />
                    <div className="flex items-center gap-2 mb-2">
                      <ExchangeIcon exchange={ex.exchange} size={22} />
                      <span className="text-sm font-semibold text-white">{EXCHANGE_LABELS[ex.exchange] || ex.exchange}</span>
                    </div>
                    <p className="text-lg font-bold tabular-nums" style={{ color: hasData ? color : '#6B7280' }}>
                      {formatCurrency(ex.total)}
                    </p>
                    <div className="mt-1.5">
                      <StatusBadge status={status} exchange={ex.exchange} t={t} />
                    </div>
                    {(data?.signups?.by_exchange?.[ex.exchange] ?? 0) > 0 && (
                      <p className="text-[10px] text-primary-400 mt-1">
                        {data.signups.by_exchange[ex.exchange]} {data.signups.by_exchange[ex.exchange] !== 1 ? t('admin.signups') : t('admin.signup')}
                      </p>
                    )}
                  </div>
                )
              })}
            </div>
            <div className="mt-3 flex items-start gap-2 text-[11px] text-amber-400/80 bg-amber-500/[0.04] border border-amber-500/10 rounded-lg p-2.5">
              <AlertTriangle size={13} className="mt-0.5 shrink-0" />
              <span>
                <strong>Bitunix:</strong> {t('admin.bitunixNote')}
              </span>
            </div>
          </div>
        </div>
      ) : (
        <div className="text-center text-gray-500 py-12 text-sm">{t('admin.noData')}</div>
      )}
    </div>
  )
}
