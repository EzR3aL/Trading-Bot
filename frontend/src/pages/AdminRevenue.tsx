import { useCallback, useEffect, useState } from 'react'
import { DollarSign } from 'lucide-react'
import api from '../api/client'
import { getApiErrorMessage } from '../utils/api-error'
import { useToastStore } from '../stores/toastStore'
import { ExchangeIcon } from '../components/ui/ExchangeLogo'

// --- Types ---

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

interface RevenueEntry {
  id: number
  date: string
  exchange: string
  type: string
  amount: number
  source: string
  notes?: string
}

interface RevenueResponse {
  summary: RevenueSummary
  by_exchange: ExchangeBreakdown[]
  entries: RevenueEntry[]
}

// --- Constants ---

const PERIODS = [
  { value: '7d', label: '7 Tage' },
  { value: '30d', label: '30 Tage' },
  { value: '90d', label: '90 Tage' },
  { value: '1y', label: '1 Jahr' },
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

// Alle Exchanges die wir tracken
const ALL_EXCHANGES = ['hyperliquid', 'bitget', 'weex', 'bingx', 'bitunix']

// --- Helpers ---

function formatCurrency(value: number): string {
  return new Intl.NumberFormat('de-DE', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value)
}

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString('de-DE', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  })
}

function getExchangeColor(exchange: string): string {
  return EXCHANGE_COLORS[exchange.toLowerCase()] || '#6B7280'
}

// --- Component ---

export default function AdminRevenue() {
  const addToast = useToastStore((s) => s.addToast)

  const [period, setPeriod] = useState('30d')
  const [data, setData] = useState<RevenueResponse | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  const loadRevenue = useCallback(async () => {
    setIsLoading(true)
    try {
      const res = await api.get<RevenueResponse>('/admin/revenue', {
        params: { period },
      })
      setData(res.data)
    } catch (err) {
      addToast('error', getApiErrorMessage(err, 'Fehler beim Laden der Einnahmen'))
    } finally {
      setIsLoading(false)
    }
  }, [period, addToast])

  useEffect(() => {
    loadRevenue()
  }, [loadRevenue])

  const summary = data?.summary

  // Exchange-Daten aufbereiten: alle Exchanges zeigen, auch mit 0
  const exchangeData = ALL_EXCHANGES.map((ex) => {
    const found = data?.by_exchange?.filter((e) => e.exchange.toLowerCase() === ex)
    const total = found?.reduce((sum, e) => sum + e.total, 0) ?? 0
    const count = found?.reduce((sum, e) => sum + e.count, 0) ?? 0
    const types = found?.map((e) => e.type).join(', ') || '-'
    return { exchange: ex, total, count, types }
  })

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-5">
        <div className="flex items-center gap-2">
          <DollarSign size={20} className="text-emerald-400" />
          <h1 className="text-2xl font-bold text-white">Einnahmen</h1>
        </div>
      </div>

      {/* Period Selector */}
      <div className="flex gap-1 mb-5 bg-gray-900 p-1 rounded-lg w-fit">
        {PERIODS.map((p) => (
          <button
            key={p.value}
            onClick={() => setPeriod(p.value)}
            className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-all ${
              period === p.value
                ? 'bg-primary-500/20 text-primary-400 ring-1 ring-primary-500/30'
                : 'text-gray-500 hover:text-white hover:bg-white/5'
            }`}
          >
            {p.label}
          </button>
        ))}
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-12">
          <div className="w-6 h-6 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin" />
        </div>
      ) : data ? (
        <div className="space-y-6">
          {/* KPI Strip */}
          {summary && (
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              {[
                { label: 'Heute', value: summary.today },
                { label: '7 Tage', value: summary.last_7d },
                { label: '30 Tage', value: summary.last_30d },
                { label: 'Gesamt', value: summary.total },
              ].map((kpi) => (
                <div
                  key={kpi.label}
                  className="border border-white/[0.08] bg-white/[0.02] rounded-xl p-4 hover:bg-white/[0.04] transition-colors"
                >
                  <p className="text-[10px] text-gray-400 uppercase tracking-wider mb-1">{kpi.label}</p>
                  <p className="text-xl font-bold text-emerald-400 tabular-nums">
                    {formatCurrency(kpi.value)}
                  </p>
                </div>
              ))}
            </div>
          )}

          {/* Exchange Cards — immer alle 5 zeigen */}
          <div>
            <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wider mb-3">
              Nach Exchange
            </h3>
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
              {exchangeData.map((ex) => {
                const color = getExchangeColor(ex.exchange)
                const hasData = ex.total > 0
                return (
                  <div
                    key={ex.exchange}
                    className={`border rounded-xl p-4 relative overflow-hidden transition-colors ${
                      hasData
                        ? 'border-white/[0.08] bg-white/[0.02] hover:bg-white/[0.04]'
                        : 'border-white/[0.05] bg-white/[0.01] opacity-60'
                    }`}
                  >
                    <div
                      className="absolute top-0 left-0 w-full h-0.5"
                      style={{ backgroundColor: color, opacity: hasData ? 1 : 0.3 }}
                    />
                    <div className="flex items-center gap-2 mb-2">
                      <ExchangeIcon exchange={ex.exchange} size={22} />
                      <span className="text-sm font-semibold text-white">
                        {EXCHANGE_LABELS[ex.exchange] || ex.exchange}
                      </span>
                    </div>
                    <p className="text-lg font-bold tabular-nums" style={{ color: hasData ? color : '#6B7280' }}>
                      {formatCurrency(ex.total)}
                    </p>
                    <p className="text-[10px] text-gray-500 mt-1">
                      {hasData
                        ? `${ex.count} ${ex.count === 1 ? 'Trade' : 'Trades'} · ${ex.types}`
                        : 'Keine Daten'}
                    </p>
                  </div>
                )
              })}
            </div>
          </div>

          {/* Entries Table — nur wenn Einträge vorhanden */}
          {data.entries.length > 0 && (
            <div>
              <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wider mb-3">
                Letzte Einträge
              </h3>

              {/* Desktop table */}
              <div className="hidden md:block overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-[11px] text-gray-500 uppercase tracking-wider border-b border-white/5">
                      <th className="pb-2 pr-3">Datum</th>
                      <th className="pb-2 pr-3">Exchange</th>
                      <th className="pb-2 pr-3">Typ</th>
                      <th className="pb-2 pr-3 text-right">Betrag</th>
                      <th className="pb-2 pr-3">Quelle</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.entries.map((entry) => (
                      <tr
                        key={entry.id}
                        className="border-b border-white/5 hover:bg-white/[0.02] transition-colors"
                      >
                        <td className="py-2.5 pr-3 text-gray-400 text-xs">
                          {formatDate(entry.date)}
                        </td>
                        <td className="py-2.5 pr-3">
                          <div className="flex items-center gap-1.5">
                            <ExchangeIcon exchange={entry.exchange} size={16} />
                            <span
                              className="text-xs font-medium"
                              style={{ color: getExchangeColor(entry.exchange) }}
                            >
                              {EXCHANGE_LABELS[entry.exchange.toLowerCase()] || entry.exchange}
                            </span>
                          </div>
                        </td>
                        <td className="py-2.5 pr-3 text-gray-400 text-xs">{entry.type}</td>
                        <td className="py-2.5 pr-3 text-right text-emerald-400 font-medium tabular-nums">
                          {formatCurrency(entry.amount)}
                        </td>
                        <td className="py-2.5 pr-3 text-gray-500 text-xs">{entry.source}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Mobile cards */}
              <div className="md:hidden space-y-2">
                {data.entries.map((entry) => (
                  <div
                    key={entry.id}
                    className="border border-white/10 bg-white/[0.03] rounded-xl p-3"
                  >
                    <div className="flex items-center justify-between mb-1">
                      <div className="flex items-center gap-1.5">
                        <ExchangeIcon exchange={entry.exchange} size={16} />
                        <span
                          className="text-xs font-medium"
                          style={{ color: getExchangeColor(entry.exchange) }}
                        >
                          {EXCHANGE_LABELS[entry.exchange.toLowerCase()] || entry.exchange}
                        </span>
                      </div>
                      <span className="text-[10px] text-gray-500">
                        {formatDate(entry.date)}
                      </span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-emerald-400 font-medium tabular-nums">
                        {formatCurrency(entry.amount)}
                      </span>
                      <span className="text-[10px] text-gray-600">{entry.type}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      ) : (
        <div className="text-center text-gray-500 py-12 text-sm">
          Keine Daten verfügbar
        </div>
      )}
    </div>
  )
}
