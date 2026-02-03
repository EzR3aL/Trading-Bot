import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import api from '../api/client'

interface TaxData {
  year: number
  total_trades: number
  total_pnl: number
  total_fees: number
  total_funding: number
  net_pnl: number
  months: { month: string; trades: number; pnl: number; fees: number }[]
}

export default function TaxReport() {
  const { t } = useTranslation()
  const currentYear = new Date().getFullYear()
  const [year, setYear] = useState(currentYear)
  const [data, setData] = useState<TaxData | null>(null)

  useEffect(() => {
    const load = async () => {
      try {
        const res = await api.get(`/tax-report?year=${year}`)
        setData(res.data)
      } catch { /* ignore */ }
    }
    load()
  }, [year])

  const downloadCsv = () => {
    window.open(`/api/tax-report/csv?year=${year}`, '_blank')
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-white">{t('tax.title')}</h1>
        <div className="flex gap-3">
          <select
            value={year}
            onChange={(e) => setYear(Number(e.target.value))}
            className="bg-gray-800 border border-gray-700 text-white rounded px-3 py-2"
          >
            {Array.from({ length: 5 }, (_, i) => currentYear - i).map((y) => (
              <option key={y} value={y}>{y}</option>
            ))}
          </select>
          <button
            onClick={downloadCsv}
            className="px-4 py-2 bg-primary-600 text-white rounded hover:bg-primary-700"
          >
            {t('tax.downloadCsv')}
          </button>
        </div>
      </div>

      {data && (
        <>
          {/* Summary */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
            <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
              <div className="text-sm text-gray-400">{t('dashboard.totalTrades')}</div>
              <div className="text-2xl font-bold text-white mt-1">{data.total_trades}</div>
            </div>
            <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
              <div className="text-sm text-gray-400">{t('tax.totalPnl')}</div>
              <div className={`text-2xl font-bold mt-1 ${data.total_pnl >= 0 ? 'text-profit' : 'text-loss'}`}>
                ${data.total_pnl.toFixed(2)}
              </div>
            </div>
            <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
              <div className="text-sm text-gray-400">{t('tax.totalFees')}</div>
              <div className="text-2xl font-bold text-white mt-1">${data.total_fees.toFixed(2)}</div>
            </div>
            <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
              <div className="text-sm text-gray-400">{t('tax.netPnl')}</div>
              <div className={`text-2xl font-bold mt-1 ${data.net_pnl >= 0 ? 'text-profit' : 'text-loss'}`}>
                ${data.net_pnl.toFixed(2)}
              </div>
            </div>
          </div>

          {/* Monthly breakdown */}
          <div className="bg-gray-900 border border-gray-800 rounded-lg">
            <div className="p-4 border-b border-gray-800">
              <h2 className="text-lg font-semibold text-white">{t('tax.monthlyBreakdown')}</h2>
            </div>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-800">
                  <th className="text-left p-3 text-gray-400">Monat</th>
                  <th className="text-right p-3 text-gray-400">Trades</th>
                  <th className="text-right p-3 text-gray-400">PnL</th>
                  <th className="text-right p-3 text-gray-400">Fees</th>
                  <th className="text-right p-3 text-gray-400">Net</th>
                </tr>
              </thead>
              <tbody>
                {data.months.map((m) => (
                  <tr key={m.month} className="border-b border-gray-800/50">
                    <td className="p-3 text-white">{m.month}</td>
                    <td className="p-3 text-right text-gray-300">{m.trades}</td>
                    <td className={`p-3 text-right ${m.pnl >= 0 ? 'text-profit' : 'text-loss'}`}>
                      ${m.pnl.toFixed(2)}
                    </td>
                    <td className="p-3 text-right text-gray-300">${m.fees.toFixed(2)}</td>
                    <td className={`p-3 text-right ${m.pnl - m.fees >= 0 ? 'text-profit' : 'text-loss'}`}>
                      ${(m.pnl - m.fees).toFixed(2)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}
