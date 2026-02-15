import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import api from '../api/client'
import { useFilterStore } from '../stores/filterStore'
import { SkeletonCard, SkeletonTable } from '../components/ui/Skeleton'
import { Download, ArrowUpRight, ArrowDownRight, Loader2 } from 'lucide-react'
import FilterDropdown from '../components/ui/FilterDropdown'

interface TaxData {
  year: number
  total_trades: number
  total_pnl: number
  total_fees: number
  total_funding: number
  net_pnl: number
  months: { month: string; trades: number; pnl: number; fees: number }[]
}

function formatPnl(value: number): string {
  const prefix = value >= 0 ? '+' : ''
  return `${prefix}$${value.toFixed(2)}`
}

export default function TaxReport() {
  const { t } = useTranslation()
  const { demoFilter } = useFilterStore()
  const currentYear = new Date().getFullYear()
  const [year, setYear] = useState(currentYear)
  const [data, setData] = useState<TaxData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    const load = async () => {
      setLoading(true)
      setError('')
      try {
        const demoParam = demoFilter === 'demo' ? '&demo_mode=true' : demoFilter === 'live' ? '&demo_mode=false' : ''
        const res = await api.get(`/tax-report?year=${year}${demoParam}`)
        setData(res.data)
      } catch {
        setError(t('common.error'))
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [year, demoFilter])

  const [downloading, setDownloading] = useState(false)

  const downloadCsv = async () => {
    setDownloading(true)
    try {
      const demoParam = demoFilter === 'demo' ? '&demo_mode=true' : demoFilter === 'live' ? '&demo_mode=false' : ''
      const res = await api.get(`/tax-report/csv?year=${year}${demoParam}`, {
        responseType: 'blob',
      })
      const url = window.URL.createObjectURL(new Blob([res.data], { type: 'text/csv; charset=utf-8' }))
      const link = document.createElement('a')
      link.href = url
      link.download = `steuerreport_${year}.csv`
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
    } catch {
      setError(t('tax.downloadError', 'Download fehlgeschlagen'))
    } finally {
      setDownloading(false)
    }
  }

  return (
    <div className="animate-in">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-white tracking-tight">{t('tax.title')}</h1>
        <div className="flex gap-3">
          <FilterDropdown
            value={String(year)}
            onChange={val => setYear(Number(val))}
            options={Array.from({ length: 5 }, (_, i) => ({ value: String(currentYear - i), label: String(currentYear - i) }))}
            ariaLabel={t('tax.year')}
          />
          <button
            onClick={downloadCsv}
            disabled={downloading}
            aria-label={t('tax.downloadCsv')}
            className="btn-gradient flex items-center gap-2 disabled:opacity-50"
          >
            {downloading ? <Loader2 size={16} className="animate-spin" /> : <Download size={16} />}
            {t('tax.downloadCsv')}
          </button>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="mb-4 p-3 bg-red-500/10 border border-red-500/20 rounded-xl text-red-400 text-sm">
          {error}
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div className="space-y-6">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <SkeletonCard key={i} />
            ))}
          </div>
          <SkeletonTable rows={6} cols={5} />
        </div>
      )}

      {!loading && data && (
        <>
          {/* Summary */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
            <div className="glass-card rounded-xl p-5">
              <div className="text-xs font-medium text-gray-400 uppercase tracking-wider mb-2">{t('dashboard.totalTrades')}</div>
              <div className="text-2xl font-bold text-white">{data.total_trades}</div>
            </div>
            <div className="glass-card rounded-xl p-5">
              <div className="text-xs font-medium text-gray-400 uppercase tracking-wider mb-2">{t('tax.totalPnl')}</div>
              <div className={`text-2xl font-bold flex items-center gap-1 ${data.total_pnl >= 0 ? 'text-profit' : 'text-loss'}`}>
                {formatPnl(data.total_pnl)}
                {data.total_pnl >= 0 ? <ArrowUpRight size={18} /> : <ArrowDownRight size={18} />}
              </div>
            </div>
            <div className="glass-card rounded-xl p-5">
              <div className="text-xs font-medium text-gray-400 uppercase tracking-wider mb-2">{t('tax.totalFees')}</div>
              <div className="text-2xl font-bold text-white">${data.total_fees.toFixed(2)}</div>
            </div>
            <div className="glass-card rounded-xl p-5">
              <div className="text-xs font-medium text-gray-400 uppercase tracking-wider mb-2">{t('tax.netPnl')}</div>
              <div className={`text-2xl font-bold flex items-center gap-1 ${data.net_pnl >= 0 ? 'text-profit' : 'text-loss'}`}>
                {formatPnl(data.net_pnl)}
                {data.net_pnl >= 0 ? <ArrowUpRight size={18} /> : <ArrowDownRight size={18} />}
              </div>
            </div>
          </div>

          {/* Monthly breakdown */}
          <div className="glass-card rounded-xl overflow-hidden">
            <div className="p-5 border-b border-white/5">
              <h2 className="text-base font-semibold text-white">{t('tax.monthlyBreakdown')}</h2>
            </div>
            <div className="overflow-x-auto">
              <table className="table-premium">
                <thead>
                  <tr>
                    <th className="text-left">{t('tax.month')}</th>
                    <th className="text-right">{t('tax.trades')}</th>
                    <th className="text-right">{t('tax.pnl')}</th>
                    <th className="text-right">{t('tax.fees')}</th>
                    <th className="text-right">{t('tax.net')}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.months.map((m) => (
                    <tr key={m.month}>
                      <td className="text-white font-medium">{m.month}</td>
                      <td className="text-right text-gray-300">{m.trades}</td>
                      <td className="text-right">
                        <span className={m.pnl >= 0 ? 'pnl-positive' : 'pnl-negative'}>
                          {formatPnl(m.pnl)}
                        </span>
                      </td>
                      <td className="text-right text-gray-300">${m.fees.toFixed(2)}</td>
                      <td className="text-right">
                        <span className={m.pnl - m.fees >= 0 ? 'pnl-positive' : 'pnl-negative'}>
                          {formatPnl(m.pnl - m.fees)}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
