import { useCallback, useEffect, useRef, useState } from 'react'
import { DollarSign, Plus, Pencil, Trash2, X } from 'lucide-react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Legend,
} from 'recharts'
import api from '../api/client'
import { getApiErrorMessage } from '../utils/api-error'
import { useToastStore } from '../stores/toastStore'
import { ExchangeIcon } from '../components/ui/ExchangeLogo'
import ConfirmModal from '../components/ui/ConfirmModal'

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

interface DailyRevenue {
  date: string
  total: number
  by_exchange: Record<string, number>
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
  daily: DailyRevenue[]
  entries: RevenueEntry[]
}

interface EntryFormData {
  date: string
  exchange: string
  revenue_type: string
  amount_usd: string
  notes: string
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

const ALL_EXCHANGES = ['hyperliquid', 'bitget', 'weex', 'bingx', 'bitunix']

const REVENUE_TYPES = ['affiliate', 'builder_fee', 'referral', 'commission']

const EMPTY_FORM: EntryFormData = {
  date: new Date().toISOString().slice(0, 10),
  exchange: 'bitget',
  revenue_type: 'affiliate',
  amount_usd: '',
  notes: '',
}

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

function formatChartDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString('de-DE', {
    day: '2-digit',
    month: '2-digit',
  })
}

function getExchangeColor(exchange: string): string {
  return EXCHANGE_COLORS[exchange.toLowerCase()] || '#6B7280'
}

// --- Revenue Chart ---

function RevenueTimeChart({ data }: { data: DailyRevenue[] }) {
  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center h-[200px] text-gray-500 text-sm">
        Keine Daten
      </div>
    )
  }

  const chartData = data.map((d) => ({
    date: formatChartDate(d.date),
    ...Object.fromEntries(
      ALL_EXCHANGES.map((ex) => [ex, d.by_exchange[ex] ?? 0])
    ),
    total: d.total,
  }))

  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart data={chartData} margin={{ top: 5, right: 10, left: 10, bottom: 5 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
        <XAxis dataKey="date" tick={{ fill: '#9ca3af', fontSize: 10 }} tickLine={false} />
        <YAxis
          width={50}
          tick={{ fill: '#9ca3af', fontSize: 10 }}
          tickLine={false}
          tickFormatter={(v) => `$${v}`}
        />
        <Tooltip
          contentStyle={{
            backgroundColor: '#1f2937',
            border: '1px solid rgba(255,255,255,0.1)',
            borderRadius: '8px',
            fontSize: '12px',
          }}
          labelStyle={{ color: '#9ca3af' }}
          formatter={(value: number, name: string) => [
            formatCurrency(value),
            EXCHANGE_LABELS[name] || name,
          ]}
        />
        <Legend
          wrapperStyle={{ fontSize: '11px' }}
          formatter={(value) => (
            <span className="text-gray-400">{EXCHANGE_LABELS[value] || value}</span>
          )}
        />
        {ALL_EXCHANGES.map((ex) => (
          <Bar
            key={ex}
            dataKey={ex}
            name={ex}
            stackId="revenue"
            fill={EXCHANGE_COLORS[ex]}
            radius={ex === ALL_EXCHANGES[ALL_EXCHANGES.length - 1] ? [2, 2, 0, 0] : [0, 0, 0, 0]}
          />
        ))}
      </BarChart>
    </ResponsiveContainer>
  )
}

// --- Entry Form Modal ---

function EntryFormModal({
  open,
  entry,
  onSave,
  onClose,
}: {
  open: boolean
  entry: RevenueEntry | null
  onSave: (data: EntryFormData, id?: number) => Promise<void>
  onClose: () => void
}) {
  const [form, setForm] = useState<EntryFormData>(EMPTY_FORM)
  const [isSaving, setIsSaving] = useState(false)
  const firstInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!open) return
    if (entry) {
      setForm({
        date: entry.date,
        exchange: entry.exchange,
        revenue_type: entry.type,
        amount_usd: String(entry.amount),
        notes: entry.notes || '',
      })
    } else {
      setForm(EMPTY_FORM)
    }
    setTimeout(() => firstInputRef.current?.focus(), 50)
  }, [open, entry])

  useEffect(() => {
    if (!open) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [open, onClose])

  if (!open) return null

  const isEdit = !!entry

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setIsSaving(true)
    try {
      await onSave(form, entry?.id)
    } finally {
      setIsSaving(false)
    }
  }

  const inputClass =
    'w-full bg-gray-800 border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:ring-2 focus:ring-primary-500/50'
  const labelClass = 'block text-xs text-gray-400 mb-1'

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
    >
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div className="relative glass-card p-6 max-w-md w-full rounded-xl shadow-2xl">
        <button
          onClick={onClose}
          className="absolute top-3 right-3 text-gray-400 hover:text-white p-1"
        >
          <X size={18} />
        </button>

        <h3 className="text-lg font-semibold text-white mb-4">
          {isEdit ? 'Eintrag bearbeiten' : 'Neuer Eintrag'}
        </h3>

        <form onSubmit={handleSubmit} className="space-y-3">
          <div>
            <label className={labelClass}>Datum</label>
            <input
              ref={firstInputRef}
              type="date"
              value={form.date}
              onChange={(e) => setForm({ ...form, date: e.target.value })}
              className={inputClass}
              required
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={labelClass}>Exchange</label>
              <select
                value={form.exchange}
                onChange={(e) => setForm({ ...form, exchange: e.target.value })}
                className={inputClass}
              >
                {ALL_EXCHANGES.map((ex) => (
                  <option key={ex} value={ex}>
                    {EXCHANGE_LABELS[ex]}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className={labelClass}>Typ</label>
              <select
                value={form.revenue_type}
                onChange={(e) => setForm({ ...form, revenue_type: e.target.value })}
                className={inputClass}
              >
                {REVENUE_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div>
            <label className={labelClass}>Betrag (USD)</label>
            <input
              type="number"
              step="0.01"
              min="0.01"
              value={form.amount_usd}
              onChange={(e) => setForm({ ...form, amount_usd: e.target.value })}
              className={inputClass}
              placeholder="0.00"
              required
            />
          </div>

          <div>
            <label className={labelClass}>Notizen (optional)</label>
            <input
              type="text"
              value={form.notes}
              onChange={(e) => setForm({ ...form, notes: e.target.value })}
              className={inputClass}
              placeholder="z.B. Bitget Q1 Abrechnung"
            />
          </div>

          <div className="flex justify-end gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              disabled={isSaving}
              className="px-4 py-2 text-sm rounded-lg bg-gray-700 hover:bg-gray-600 text-white transition-colors"
            >
              Abbrechen
            </button>
            <button
              type="submit"
              disabled={isSaving || !form.amount_usd}
              className="px-4 py-2 text-sm rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white transition-colors flex items-center gap-2 disabled:opacity-60 disabled:cursor-not-allowed"
            >
              {isSaving && (
                <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
              )}
              {isEdit ? 'Speichern' : 'Anlegen'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// --- Main Component ---

export default function AdminRevenue() {
  const addToast = useToastStore((s) => s.addToast)

  const [period, setPeriod] = useState('30d')
  const [data, setData] = useState<RevenueResponse | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  // Modal state
  const [isFormOpen, setIsFormOpen] = useState(false)
  const [editingEntry, setEditingEntry] = useState<RevenueEntry | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<RevenueEntry | null>(null)
  const [isDeleting, setIsDeleting] = useState(false)

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

  const handleSave = async (formData: EntryFormData, id?: number) => {
    const payload = {
      date: formData.date,
      exchange: formData.exchange,
      revenue_type: formData.revenue_type,
      amount_usd: parseFloat(formData.amount_usd),
      notes: formData.notes || null,
    }
    try {
      if (id) {
        await api.put(`/admin/revenue/${id}`, payload)
        addToast('success', 'Eintrag aktualisiert')
      } else {
        await api.post('/admin/revenue', payload)
        addToast('success', 'Eintrag angelegt')
      }
      setIsFormOpen(false)
      setEditingEntry(null)
      await loadRevenue()
    } catch (err) {
      addToast('error', getApiErrorMessage(err, 'Fehler beim Speichern'))
    }
  }

  const handleDelete = async () => {
    if (!deleteTarget) return
    setIsDeleting(true)
    try {
      await api.delete(`/admin/revenue/${deleteTarget.id}`)
      addToast('success', 'Eintrag gelöscht')
      setDeleteTarget(null)
      await loadRevenue()
    } catch (err) {
      addToast('error', getApiErrorMessage(err, 'Fehler beim Löschen'))
    } finally {
      setIsDeleting(false)
    }
  }

  const openCreate = () => {
    setEditingEntry(null)
    setIsFormOpen(true)
  }

  const openEdit = (entry: RevenueEntry) => {
    setEditingEntry(entry)
    setIsFormOpen(true)
  }

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
        <button
          onClick={openCreate}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white transition-colors"
        >
          <Plus size={14} />
          Neuer Eintrag
        </button>
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

          {/* Revenue Chart */}
          {data.daily.length > 0 && (
            <div>
              <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wider mb-3">
                Zeitverlauf
              </h3>
              <div className="border border-white/[0.08] bg-white/[0.02] rounded-xl p-4">
                <RevenueTimeChart data={data.daily} />
              </div>
            </div>
          )}

          {/* Exchange Cards */}
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

          {/* Entries Table */}
          <div>
            <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wider mb-3">
              {data.entries.length > 0 ? 'Letzte Einträge' : 'Einträge'}
            </h3>

            {data.entries.length === 0 ? (
              <div className="text-center text-gray-500 py-8 text-sm border border-white/5 rounded-xl">
                Noch keine manuellen Einträge vorhanden
              </div>
            ) : (
              <>
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
                        <th className="pb-2 w-20"></th>
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
                          <td className="py-2.5">
                            {entry.source === 'manual' && (
                              <div className="flex items-center gap-1">
                                <button
                                  onClick={() => openEdit(entry)}
                                  className="p-1 text-gray-500 hover:text-white transition-colors"
                                  title="Bearbeiten"
                                >
                                  <Pencil size={14} />
                                </button>
                                <button
                                  onClick={() => setDeleteTarget(entry)}
                                  className="p-1 text-gray-500 hover:text-red-400 transition-colors"
                                  title="Löschen"
                                >
                                  <Trash2 size={14} />
                                </button>
                              </div>
                            )}
                          </td>
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
                        <div className="flex items-center gap-2">
                          {entry.source === 'manual' && (
                            <div className="flex items-center gap-1">
                              <button
                                onClick={() => openEdit(entry)}
                                className="p-1 text-gray-500 hover:text-white"
                              >
                                <Pencil size={12} />
                              </button>
                              <button
                                onClick={() => setDeleteTarget(entry)}
                                className="p-1 text-gray-500 hover:text-red-400"
                              >
                                <Trash2 size={12} />
                              </button>
                            </div>
                          )}
                          <span className="text-[10px] text-gray-500">
                            {formatDate(entry.date)}
                          </span>
                        </div>
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
              </>
            )}
          </div>
        </div>
      ) : (
        <div className="text-center text-gray-500 py-12 text-sm">
          Keine Daten verfügbar
        </div>
      )}

      {/* Create/Edit Modal */}
      <EntryFormModal
        open={isFormOpen}
        entry={editingEntry}
        onSave={handleSave}
        onClose={() => {
          setIsFormOpen(false)
          setEditingEntry(null)
        }}
      />

      {/* Delete Confirmation */}
      <ConfirmModal
        open={!!deleteTarget}
        title="Eintrag löschen"
        message={
          deleteTarget
            ? `${EXCHANGE_LABELS[deleteTarget.exchange.toLowerCase()] || deleteTarget.exchange} — ${formatCurrency(deleteTarget.amount)} vom ${formatDate(deleteTarget.date)} wirklich löschen?`
            : ''
        }
        confirmLabel="Löschen"
        variant="danger"
        onConfirm={handleDelete}
        onCancel={() => setDeleteTarget(null)}
        loading={isDeleting}
      />
    </div>
  )
}
