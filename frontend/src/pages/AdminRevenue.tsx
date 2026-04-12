import { useCallback, useEffect, useState } from 'react'
import { DollarSign, Plus, Pencil, Trash2, X } from 'lucide-react'
import api from '../api/client'
import { getApiErrorMessage } from '../utils/api-error'
import { useToastStore } from '../stores/toastStore'
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
  is_manual: boolean
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

const EMPTY_FORM = {
  date: new Date().toISOString().slice(0, 10),
  exchange: 'hyperliquid',
  type: 'affiliate',
  amount: '',
  source: '',
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

function getExchangeColor(exchange: string): string {
  return EXCHANGE_COLORS[exchange.toLowerCase()] || '#6B7280'
}

// --- Component ---

export default function AdminRevenue() {
  const addToast = useToastStore((s) => s.addToast)

  const [period, setPeriod] = useState('30d')
  const [data, setData] = useState<RevenueResponse | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  // Form state
  const [isFormOpen, setIsFormOpen] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [form, setForm] = useState({ ...EMPTY_FORM })
  const [isSubmitting, setIsSubmitting] = useState(false)

  // Delete confirm
  const [confirmModal, setConfirmModal] = useState<{
    open: boolean
    title: string
    message: string
    variant: 'danger' | 'warning' | 'info'
    onConfirm: () => void
  }>({ open: false, title: '', message: '', variant: 'danger', onConfirm: () => {} })

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

  const resetForm = () => {
    setForm({ ...EMPTY_FORM })
    setEditingId(null)
    setIsFormOpen(false)
  }

  const handleEdit = (entry: RevenueEntry) => {
    setForm({
      date: entry.date.slice(0, 10),
      exchange: entry.exchange,
      type: entry.type,
      amount: String(entry.amount),
      source: entry.source,
      notes: entry.notes || '',
    })
    setEditingId(entry.id)
    setIsFormOpen(true)
  }

  const handleSubmit = async () => {
    if (!form.amount || isNaN(Number(form.amount))) {
      addToast('error', 'Betrag ist erforderlich')
      return
    }
    setIsSubmitting(true)
    try {
      const payload = {
        date: form.date,
        exchange: form.exchange,
        type: form.type,
        amount: Number(form.amount),
        source: form.source || 'manual',
        notes: form.notes || null,
      }
      if (editingId) {
        await api.put(`/admin/revenue/${editingId}`, payload)
        addToast('success', 'Eintrag aktualisiert')
      } else {
        await api.post('/admin/revenue', payload)
        addToast('success', 'Eintrag hinzugefügt')
      }
      resetForm()
      loadRevenue()
    } catch (err) {
      addToast('error', getApiErrorMessage(err, 'Fehler beim Speichern'))
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleDelete = (entry: RevenueEntry) => {
    setConfirmModal({
      open: true,
      title: 'Eintrag löschen',
      message: `Eintrag vom ${formatDate(entry.date)} (${formatCurrency(entry.amount)}) wirklich löschen?`,
      variant: 'danger',
      onConfirm: async () => {
        try {
          await api.delete(`/admin/revenue/${entry.id}`)
          addToast('success', 'Eintrag gelöscht')
          loadRevenue()
        } catch (err) {
          addToast('error', getApiErrorMessage(err, 'Fehler beim Löschen'))
        }
        setConfirmModal((prev) => ({ ...prev, open: false }))
      },
    })
  }

  const summary = data?.summary

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-5">
        <div className="flex items-center gap-2">
          <DollarSign size={20} className="text-emerald-400" />
          <h1 className="text-2xl font-bold text-white">Einnahmen</h1>
        </div>
        <button
          onClick={() => { setEditingId(null); setForm({ ...EMPTY_FORM }); setIsFormOpen(!isFormOpen) }}
          className="px-3 py-1.5 text-sm bg-primary-600 text-white rounded-lg hover:bg-primary-700 transition-colors flex items-center gap-1.5"
        >
          <Plus size={14} />
          Eintrag hinzufügen
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

      {/* Add/Edit Form */}
      {isFormOpen && (
        <div className="border border-white/10 bg-white/[0.03] rounded-xl p-5 mb-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-semibold text-white">
              {editingId ? 'Eintrag bearbeiten' : 'Neuer Eintrag'}
            </h2>
            <button onClick={resetForm} className="p-1 text-gray-400 hover:text-white transition-colors">
              <X size={16} />
            </button>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 max-w-3xl">
            <div>
              <label className="block text-xs text-gray-400 mb-1">Datum</label>
              <input
                type="date"
                value={form.date}
                onChange={(e) => setForm({ ...form, date: e.target.value })}
                className="filter-select w-full text-sm"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-400 mb-1">Exchange</label>
              <select
                value={form.exchange}
                onChange={(e) => setForm({ ...form, exchange: e.target.value })}
                className="filter-select w-full text-sm"
              >
                {Object.entries(EXCHANGE_LABELS).map(([key, label]) => (
                  <option key={key} value={key}>{label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs text-gray-400 mb-1">Typ</label>
              <select
                value={form.type}
                onChange={(e) => setForm({ ...form, type: e.target.value })}
                className="filter-select w-full text-sm"
              >
                <option value="affiliate">Affiliate</option>
                <option value="builder_fee">Builder Fee</option>
                <option value="referral">Referral</option>
                <option value="other">Sonstiges</option>
              </select>
            </div>
            <div>
              <label className="block text-xs text-gray-400 mb-1">Betrag (USD)</label>
              <input
                type="number"
                step="0.01"
                value={form.amount}
                onChange={(e) => setForm({ ...form, amount: e.target.value })}
                placeholder="0.00"
                className="filter-select w-full text-sm"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-400 mb-1">Quelle</label>
              <input
                type="text"
                value={form.source}
                onChange={(e) => setForm({ ...form, source: e.target.value })}
                placeholder="z.B. manual, api-sync"
                className="filter-select w-full text-sm"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-400 mb-1">Notizen</label>
              <input
                type="text"
                value={form.notes}
                onChange={(e) => setForm({ ...form, notes: e.target.value })}
                placeholder="Optional"
                className="filter-select w-full text-sm"
              />
            </div>
          </div>
          <div className="flex gap-2 mt-4">
            <button
              onClick={handleSubmit}
              disabled={isSubmitting || !form.amount}
              className="px-3 py-1.5 text-sm bg-primary-600 text-white rounded-lg hover:bg-primary-700 transition-colors disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-1.5"
            >
              {isSubmitting && <div className="w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin" />}
              {editingId ? 'Speichern' : 'Hinzufügen'}
            </button>
            <button
              onClick={resetForm}
              className="px-3 py-1.5 text-sm bg-white/5 border border-white/10 text-gray-300 rounded-lg hover:bg-white/10 transition-colors"
            >
              Abbrechen
            </button>
          </div>
        </div>
      )}

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

          {/* Exchange Cards */}
          {data.by_exchange && data.by_exchange.length > 0 && (
            <div>
              <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wider mb-3">
                Nach Exchange
              </h3>
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
                {data.by_exchange.map((ex) => {
                  const color = getExchangeColor(ex.exchange)
                  return (
                    <div
                      key={ex.exchange}
                      className="border border-white/[0.08] bg-white/[0.02] rounded-xl p-4 hover:bg-white/[0.04] transition-colors relative overflow-hidden"
                    >
                      <div
                        className="absolute top-0 left-0 w-full h-0.5"
                        style={{ backgroundColor: color }}
                      />
                      <p className="text-xs font-medium mb-1" style={{ color }}>
                        {EXCHANGE_LABELS[ex.exchange.toLowerCase()] || ex.exchange}
                      </p>
                      <p className="text-lg font-bold text-white tabular-nums">
                        {formatCurrency(ex.total)}
                      </p>
                      <p className="text-[10px] text-gray-500 mt-0.5">
                        {ex.count} {ex.count === 1 ? 'Eintrag' : 'Einträge'}
                      </p>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* Entries Table */}
          <div>
            <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wider mb-3">
              Einträge
            </h3>
            {data.entries.length === 0 ? (
              <div className="text-center text-gray-500 py-8 text-sm">
                Keine Einträge im gewählten Zeitraum
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
                        <th className="pb-2 pr-3">Notizen</th>
                        <th className="pb-2"></th>
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
                            <span
                              className="text-xs font-medium"
                              style={{ color: getExchangeColor(entry.exchange) }}
                            >
                              {EXCHANGE_LABELS[entry.exchange.toLowerCase()] || entry.exchange}
                            </span>
                          </td>
                          <td className="py-2.5 pr-3 text-gray-400 text-xs">{entry.type}</td>
                          <td className="py-2.5 pr-3 text-right text-emerald-400 font-medium tabular-nums">
                            {formatCurrency(entry.amount)}
                          </td>
                          <td className="py-2.5 pr-3 text-gray-500 text-xs">{entry.source}</td>
                          <td className="py-2.5 pr-3 text-gray-600 text-xs max-w-[150px] truncate">
                            {entry.notes || '-'}
                          </td>
                          <td className="py-2.5">
                            {entry.is_manual && (
                              <div className="flex gap-1">
                                <button
                                  onClick={() => handleEdit(entry)}
                                  title="Bearbeiten"
                                  className="p-1 text-blue-400/60 hover:text-blue-400 transition-colors"
                                >
                                  <Pencil size={14} />
                                </button>
                                <button
                                  onClick={() => handleDelete(entry)}
                                  title="Löschen"
                                  className="p-1 text-red-400/50 hover:text-red-400 transition-colors"
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
                        <span
                          className="text-xs font-medium"
                          style={{ color: getExchangeColor(entry.exchange) }}
                        >
                          {EXCHANGE_LABELS[entry.exchange.toLowerCase()] || entry.exchange}
                        </span>
                        <span className="text-[10px] text-gray-500">
                          {formatDate(entry.date)}
                        </span>
                      </div>
                      <div className="flex items-center justify-between">
                        <div>
                          <span className="text-emerald-400 font-medium tabular-nums">
                            {formatCurrency(entry.amount)}
                          </span>
                          <span className="text-[10px] text-gray-600 ml-2">{entry.type}</span>
                        </div>
                        {entry.is_manual && (
                          <div className="flex gap-1">
                            <button
                              onClick={() => handleEdit(entry)}
                              className="p-1 text-blue-400/60 hover:text-blue-400 transition-colors"
                            >
                              <Pencil size={13} />
                            </button>
                            <button
                              onClick={() => handleDelete(entry)}
                              className="p-1 text-red-400/50 hover:text-red-400 transition-colors"
                            >
                              <Trash2 size={13} />
                            </button>
                          </div>
                        )}
                      </div>
                      {entry.notes && (
                        <p className="text-[10px] text-gray-600 mt-1 truncate">{entry.notes}</p>
                      )}
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

      {/* Confirm Modal */}
      <ConfirmModal
        open={confirmModal.open}
        title={confirmModal.title}
        message={confirmModal.message}
        variant={confirmModal.variant}
        onConfirm={confirmModal.onConfirm}
        onCancel={() => setConfirmModal((prev) => ({ ...prev, open: false }))}
      />
    </div>
  )
}
