import { useEffect, useState, useCallback, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { Radio, Send, Clock, Trash2, X, Eye, XCircle, Pencil } from 'lucide-react'
import api from '../api/client'
import { getApiErrorMessage } from '../utils/api-error'
import { useToastStore } from '../stores/toastStore'
import FilterDropdown from '../components/ui/FilterDropdown'
import Pagination from '../components/ui/Pagination'
import ConfirmModal from '../components/ui/ConfirmModal'
import BroadcastPreview from '../components/broadcast/BroadcastPreview'
import BroadcastProgress from '../components/broadcast/BroadcastProgress'

interface Broadcast {
  id: number
  title: string
  message_markdown: string
  image_url?: string
  exchange_filter?: string
  status: 'draft' | 'scheduled' | 'sending' | 'completed' | 'failed' | 'cancelled'
  scheduled_at?: string
  started_at?: string
  completed_at?: string
  total_targets: number
  sent_count: number
  failed_count: number
  created_at: string
}

// Detail view for viewing sent broadcast content
function BroadcastDetailModal({ broadcast, onClose }: { broadcast: Broadcast; onClose: () => void }) {
  const { t } = useTranslation()
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div className="bg-[#0f1923] border border-white/10 rounded-xl p-5 max-w-2xl w-full mx-4 max-h-[80vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-white">{broadcast.title}</h2>
          <button
            onClick={onClose}
            aria-label={t('common.close')}
            className="p-1 text-gray-400 hover:text-white transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500/60 rounded"
          >
            <X size={18} />
          </button>
        </div>

        <div className="space-y-3 text-sm">
          <div className="flex flex-wrap gap-3 text-xs text-gray-400">
            <span>{t('broadcast.formExchangeFilter')}: {broadcast.exchange_filter || t('broadcast.allExchanges')}</span>
            <span>{t('broadcast.targets')}: {broadcast.total_targets}</span>
            <span className="text-emerald-400">{t('broadcast.successCount')}: {broadcast.sent_count}</span>
            {broadcast.failed_count > 0 && <span className="text-red-400">{t('broadcast.failureCount')}: {broadcast.failed_count}</span>}
          </div>

          <div className="border-t border-white/10 pt-3">
            <label className="block text-xs text-gray-500 mb-1">{t('broadcast.formMessage')}</label>
            <div className="bg-white/[0.03] border border-white/5 rounded-lg p-3 text-gray-200 whitespace-pre-wrap font-mono text-xs">
              {broadcast.message_markdown}
            </div>
          </div>

          {broadcast.image_url && (
            <div>
              <label className="block text-xs text-gray-500 mb-1">{t('broadcast.formImageUrl')}</label>
              <img src={broadcast.image_url} alt="" className="max-h-48 rounded-lg object-contain" />
            </div>
          )}

          <div className="text-[11px] text-gray-600 pt-2 border-t border-white/10">
            {broadcast.started_at && <span>Gesendet: {new Date(broadcast.started_at).toLocaleString('de-DE')} </span>}
            {broadcast.completed_at && <span>| Abgeschlossen: {new Date(broadcast.completed_at).toLocaleString('de-DE')}</span>}
          </div>
        </div>
      </div>
    </div>
  )
}

interface DiscordEmbed {
  title?: string
  description?: string
  color?: number
  footer?: { text?: string }
  image?: { url?: string }
}

interface PreviewApiResponse {
  total_targets: number
  by_channel: Record<string, number>
  estimated_duration_seconds: number
  preview: Record<string, string>
}

interface PreviewData {
  discord: DiscordEmbed | null
  telegram: string
  target_count: number
  discord_count: number
  telegram_count: number
  estimated_duration_seconds: number
}

function mapPreviewResponse(res: PreviewApiResponse): PreviewData {
  let discord: DiscordEmbed | null = null
  if (res.preview?.discord) {
    try {
      discord = JSON.parse(res.preview.discord)
    } catch {
      discord = null
    }
  }
  return {
    discord,
    telegram: res.preview?.telegram || '',
    target_count: res.total_targets || 0,
    discord_count: res.by_channel?.discord || 0,
    telegram_count: res.by_channel?.telegram || 0,
    estimated_duration_seconds: res.estimated_duration_seconds || 0,
  }
}

interface BroadcastListResponse {
  items: Broadcast[]
  total: number
  page: number
  per_page: number
  total_pages: number
}

const EXCHANGE_OPTIONS = [
  { value: '', label: 'Alle Exchanges' },
  { value: 'hyperliquid', label: 'Hyperliquid' },
  { value: 'bitget', label: 'Bitget' },
  { value: 'weex', label: 'Weex' },
  { value: 'bitunix', label: 'Bitunix' },
  { value: 'bingx', label: 'BingX' },
]

const STATUS_STYLES: Record<string, string> = {
  draft: 'bg-gray-500/10 text-gray-400',
  scheduled: 'bg-blue-500/10 text-blue-400',
  sending: 'bg-yellow-500/10 text-yellow-400 animate-pulse',
  completed: 'bg-emerald-500/10 text-emerald-400',
  failed: 'bg-red-500/10 text-red-400',
  cancelled: 'bg-gray-500/10 text-gray-500',
}

const PER_PAGE = 20

export default function AdminBroadcasts() {
  const { t } = useTranslation()
  const addToast = useToastStore((s) => s.addToast)

  // Form state
  const [isFormOpen, setIsFormOpen] = useState(false)
  const [formTitle, setFormTitle] = useState('')
  const [formMessage, setFormMessage] = useState('')
  const [formImageUrl, setFormImageUrl] = useState('')
  const [formExchangeFilter, setFormExchangeFilter] = useState('')
  const [isScheduled, setIsScheduled] = useState(false)
  const [scheduledAt, setScheduledAt] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)

  // Preview state
  const [previewData, setPreviewData] = useState<PreviewData | null>(null)
  const [previewBroadcastId, setPreviewBroadcastId] = useState<number | null>(null)

  // List state
  const [broadcasts, setBroadcasts] = useState<Broadcast[]>([])
  const [page, setPage] = useState(1)
  const [totalPages, setTotalPages] = useState(1)
  const [isLoading, setIsLoading] = useState(true)

  // Detail view state
  const [detailBroadcast, setDetailBroadcast] = useState<Broadcast | null>(null)

  // Confirm modal state
  const [confirmModal, setConfirmModal] = useState<{
    open: boolean
    title: string
    message: string
    variant: 'danger' | 'warning' | 'info'
    onConfirm: () => void
  }>({ open: false, title: '', message: '', variant: 'danger', onConfirm: () => {} })

  // Polling ref for sending broadcasts
  const pollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const loadBroadcasts = useCallback(async () => {
    try {
      const res = await api.get<BroadcastListResponse>('/admin/broadcasts/', {
        params: { page, per_page: PER_PAGE },
      })
      setBroadcasts(res.data.items)
      setTotalPages(res.data.total_pages)
    } catch (err) {
      addToast('error', getApiErrorMessage(err, t('common.loadError', 'Fehler beim Laden')))
    } finally {
      setIsLoading(false)
    }
  }, [page, addToast, t])

  useEffect(() => {
    loadBroadcasts()
  }, [loadBroadcasts])

  // Poll progress for any sending broadcasts
  const hasSendingBroadcasts = broadcasts.some((b) => b.status === 'sending')

  useEffect(() => {
    if (hasSendingBroadcasts) {
      pollIntervalRef.current = setInterval(async () => {
        const sendingIds = broadcasts.filter((b) => b.status === 'sending').map((b) => b.id)
        for (const id of sendingIds) {
          try {
            const res = await api.get<{ broadcast_id: number; sent: number; failed: number; total: number; status: string }>(`/admin/broadcasts/${id}/progress`)
            const progress = res.data
            setBroadcasts((prev) =>
              prev.map((b) => (b.id === id ? { ...b, status: progress.status as Broadcast['status'], sent_count: progress.sent, failed_count: progress.failed, total_targets: progress.total } : b))
            )
            // Wenn Broadcast fertig, Liste komplett neu laden
            if (progress.status !== 'sending') {
              loadBroadcasts()
            }
          } catch {
            // Silently ignore polling errors
          }
        }
      }, 3000)
    }
    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current)
        pollIntervalRef.current = null
      }
    }
  }, [hasSendingBroadcasts, broadcasts])

  const resetForm = () => {
    setFormTitle('')
    setFormMessage('')
    setFormImageUrl('')
    setFormExchangeFilter('')
    setIsScheduled(false)
    setScheduledAt('')
    setPreviewData(null)
    setPreviewBroadcastId(null)
    setIsFormOpen(false)
  }

  const handleEditDraft = (b: Broadcast) => {
    setFormTitle(b.title)
    setFormMessage(b.message_markdown)
    setFormImageUrl(b.image_url || '')
    setFormExchangeFilter(b.exchange_filter || '')
    setIsScheduled(!!b.scheduled_at)
    setScheduledAt(b.scheduled_at ? b.scheduled_at.slice(0, 16) : '')
    setPreviewBroadcastId(b.id)
    setPreviewData(null)
    setIsFormOpen(true)
    // Delete the old draft — a new one will be created on preview
    api.delete(`/admin/broadcasts/${b.id}`).catch(() => {})
    loadBroadcasts()
  }

  const handlePreviewDraft = async (b: Broadcast) => {
    setPreviewBroadcastId(b.id)
    setIsSubmitting(true)
    try {
      const previewRes = await api.post<PreviewApiResponse>(`/admin/broadcasts/${b.id}/preview`)
      setPreviewData(mapPreviewResponse(previewRes.data))
      setFormTitle(b.title)
      setFormMessage(b.message_markdown)
      setFormImageUrl(b.image_url || '')
      setFormExchangeFilter(b.exchange_filter || '')
      setIsFormOpen(true)
    } catch (err) {
      addToast('error', getApiErrorMessage(err, t('common.error', 'Fehler')))
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleCreateAndPreview = async () => {
    if (!formTitle.trim()) {
      addToast('error', t('broadcast.formTitle') + ' ist erforderlich')
      return
    }
    if (!formMessage.trim()) {
      addToast('error', t('broadcast.formMessage') + ' ist erforderlich')
      return
    }
    setIsSubmitting(true)
    try {
      // Create the broadcast as draft
      const createRes = await api.post<Broadcast>('/admin/broadcasts/', {
        title: formTitle.trim(),
        message: formMessage.trim(),
        image_url: formImageUrl.trim() || null,
        exchange_filter: formExchangeFilter || null,
        scheduled_at: isScheduled && scheduledAt ? scheduledAt : null,
      })
      const broadcastId = createRes.data.id
      setPreviewBroadcastId(broadcastId)

      // Fetch preview
      const previewRes = await api.post<PreviewApiResponse>(`/admin/broadcasts/${broadcastId}/preview`)
      setPreviewData(mapPreviewResponse(previewRes.data))
      loadBroadcasts()
    } catch (err) {
      addToast('error', getApiErrorMessage(err, t('common.error', 'Fehler')))
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleSend = async () => {
    if (!previewBroadcastId) return
    setIsSubmitting(true)
    try {
      await api.post(`/admin/broadcasts/${previewBroadcastId}/send`)
      addToast('success', t('broadcast.statusSending'))
      resetForm()
      loadBroadcasts()
    } catch (err) {
      addToast('error', getApiErrorMessage(err, t('common.error', 'Fehler')))
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleCancel = (broadcast: Broadcast) => {
    setConfirmModal({
      open: true,
      title: t('broadcast.cancel'),
      message: t('broadcast.cancelConfirm'),
      variant: 'warning',
      onConfirm: async () => {
        try {
          await api.post(`/admin/broadcasts/${broadcast.id}/cancel`)
          addToast('success', t('broadcast.statusCancelled'))
          loadBroadcasts()
        } catch (err) {
          addToast('error', getApiErrorMessage(err, t('common.error', 'Fehler')))
        }
        setConfirmModal((prev) => ({ ...prev, open: false }))
      },
    })
  }

  const handleDelete = (broadcast: Broadcast) => {
    setConfirmModal({
      open: true,
      title: t('broadcast.delete'),
      message: t('broadcast.deleteConfirm'),
      variant: 'danger',
      onConfirm: async () => {
        try {
          await api.delete(`/admin/broadcasts/${broadcast.id}`)
          addToast('success', t('broadcast.delete'))
          loadBroadcasts()
        } catch (err) {
          addToast('error', getApiErrorMessage(err, t('common.error', 'Fehler')))
        }
        setConfirmModal((prev) => ({ ...prev, open: false }))
      },
    })
  }

  const getStatusLabel = (status: string): string => {
    const labels: Record<string, string> = {
      draft: t('broadcast.statusDraft'),
      scheduled: t('broadcast.statusScheduled'),
      sending: t('broadcast.statusSending'),
      completed: t('broadcast.statusCompleted'),
      failed: t('broadcast.statusFailed'),
      cancelled: t('broadcast.statusCancelled'),
    }
    return labels[status] || status
  }

  const formatDuration = (seconds: number): string => {
    if (seconds < 60) return `~${seconds}s`
    const mins = Math.ceil(seconds / 60)
    return `~${mins} min`
  }

  const formatDateTime = (dateStr?: string): string => {
    if (!dateStr) return '-'
    return new Date(dateStr).toLocaleString('de-DE', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  const canCancel = (status: string) => status === 'scheduled' || status === 'sending'
  const canDelete = (status: string) =>
    status === 'completed' || status === 'failed' || status === 'cancelled' || status === 'draft'

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-5">
        <div className="flex items-center gap-2">
          <Radio size={20} className="text-primary-400" />
          <h1 className="text-2xl font-bold text-white">{t('broadcast.title')}</h1>
        </div>
        <button
          onClick={() => setIsFormOpen(!isFormOpen)}
          className="px-3 py-1.5 text-sm bg-primary-600 text-white rounded-lg hover:bg-primary-700 transition-colors"
        >
          + {t('broadcast.create')}
        </button>
      </div>

      {/* Create Form */}
      {isFormOpen && (
        <div className="border border-white/10 bg-white/[0.03] rounded-xl p-5 mb-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-semibold text-white">{t('broadcast.create')}</h2>
            <button
              onClick={resetForm}
              aria-label={t('common.close')}
              className="p-1 text-gray-400 hover:text-white transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500/60 rounded"
            >
              <X size={16} />
            </button>
          </div>

          <div className="space-y-3 max-w-2xl">
            {/* Title */}
            <div>
              <label className="block text-xs text-gray-400 mb-1">{t('broadcast.formTitle')}</label>
              <input
                type="text"
                maxLength={200}
                value={formTitle}
                onChange={(e) => setFormTitle(e.target.value)}
                placeholder={t('broadcast.formTitle')}
                className="filter-select w-full text-sm"
              />
              <div className="text-[10px] text-gray-600 mt-0.5 text-right">{formTitle.length}/200</div>
            </div>

            {/* Message */}
            <div>
              <label className="block text-xs text-gray-400 mb-1">{t('broadcast.formMessage')}</label>
              <textarea
                maxLength={4000}
                value={formMessage}
                onChange={(e) => setFormMessage(e.target.value)}
                placeholder={t('broadcast.formMessage')}
                rows={6}
                className="filter-select w-full text-sm font-mono resize-y"
              />
              <div className="text-[10px] text-gray-600 mt-0.5 text-right">{formMessage.length}/4000</div>
            </div>

            {/* Image URL */}
            <div>
              <label className="block text-xs text-gray-400 mb-1">{t('broadcast.formImageUrl')}</label>
              <input
                type="url"
                value={formImageUrl}
                onChange={(e) => setFormImageUrl(e.target.value)}
                placeholder="https://..."
                className="filter-select w-full text-sm"
              />
            </div>

            {/* Exchange filter + Schedule row */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className="block text-xs text-gray-400 mb-1">{t('broadcast.formExchangeFilter')}</label>
                <FilterDropdown
                  value={formExchangeFilter}
                  onChange={setFormExchangeFilter}
                  options={EXCHANGE_OPTIONS}
                  ariaLabel={t('broadcast.formExchangeFilter')}
                />
              </div>

              <div>
                <label className="block text-xs text-gray-400 mb-1">{t('broadcast.schedule')}</label>
                <div className="flex items-center gap-3">
                  <button
                    onClick={() => setIsScheduled(false)}
                    className={`px-3 py-1.5 text-xs rounded-lg transition-all ${
                      !isScheduled
                        ? 'bg-primary-500/20 text-primary-400 ring-1 ring-primary-500/30'
                        : 'text-gray-500 hover:text-white hover:bg-white/5'
                    }`}
                  >
                    {t('broadcast.sendNow')}
                  </button>
                  <button
                    onClick={() => setIsScheduled(true)}
                    className={`px-3 py-1.5 text-xs rounded-lg transition-all ${
                      isScheduled
                        ? 'bg-primary-500/20 text-primary-400 ring-1 ring-primary-500/30'
                        : 'text-gray-500 hover:text-white hover:bg-white/5'
                    }`}
                  >
                    <Clock size={12} className="inline mr-1" />
                    {t('broadcast.schedule')}
                  </button>
                </div>
                {isScheduled && (
                  <input
                    type="datetime-local"
                    value={scheduledAt}
                    onChange={(e) => setScheduledAt(e.target.value)}
                    className="filter-select w-full text-sm mt-2"
                  />
                )}
              </div>
            </div>

            {/* Action buttons */}
            <div className="flex gap-2 pt-2">
              <button
                onClick={handleCreateAndPreview}
                disabled={isSubmitting || !formTitle.trim() || !formMessage.trim()}
                className="px-3 py-1.5 text-sm bg-white/5 border border-white/10 text-gray-300 rounded-lg hover:bg-white/10 transition-colors disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-1.5"
              >
                {isSubmitting && <div className="w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin" />}
                <Eye size={14} />
                {t('broadcast.preview')}
              </button>
              <button
                onClick={resetForm}
                className="px-3 py-1.5 text-sm bg-white/5 border border-white/10 text-gray-300 rounded-lg hover:bg-white/10 transition-colors"
              >
                {t('broadcast.cancel')}
              </button>
            </div>
          </div>

          {/* Preview section */}
          {previewData && (
            <div className="mt-5 pt-5 border-t border-white/10">
              <div className="mb-3 space-y-1">
                <div className="text-sm text-white font-medium">
                  {t('broadcast.targetCount', { count: previewData.target_count })}
                </div>
                <div className="text-xs text-gray-400">
                  {t('broadcast.channelBreakdown', {
                    discord: previewData.discord_count,
                    telegram: previewData.telegram_count,
                  })}
                </div>
                <div className="text-xs text-gray-500">
                  {t('broadcast.estimatedDuration')}: {formatDuration(previewData.estimated_duration_seconds)}
                </div>
              </div>

              <BroadcastPreview
                discord={previewData.discord}
                telegram={previewData.telegram}
              />

              <div className="mt-4 flex gap-2">
                <button
                  onClick={handleSend}
                  disabled={isSubmitting}
                  className="px-4 py-2 text-sm bg-primary-600 text-white rounded-lg hover:bg-primary-700 transition-colors disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-1.5"
                >
                  {isSubmitting && <div className="w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin" />}
                  <Send size={14} />
                  {t('broadcast.confirmSend', { count: previewData.target_count })}
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* History Table */}
      {isLoading ? (
        <div className="flex items-center justify-center py-12">
          <div className="w-6 h-6 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin" />
        </div>
      ) : broadcasts.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-12 text-center">
          <Radio className="w-10 h-10 text-gray-600 dark:text-gray-600 mb-3" />
          <p className="text-gray-500 dark:text-gray-400 font-medium">{t('broadcast.noHistory')}</p>
          <p className="text-gray-400 dark:text-gray-500 text-sm mt-1">{t('broadcast.noHistoryHint')}</p>
        </div>
      ) : (
        <>
          {/* Desktop table */}
          <div className="hidden md:block overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[11px] text-gray-500 uppercase tracking-wider border-b border-white/5">
                  <th className="pb-2 pr-3">Status</th>
                  <th className="pb-2 pr-3">{t('broadcast.formTitle')}</th>
                  <th className="pb-2 pr-3">{t('broadcast.formExchangeFilter')}</th>
                  <th className="pb-2 pr-3">{t('broadcast.targets')}</th>
                  <th className="pb-2 pr-3">{t('broadcast.scheduledAt')}</th>
                  <th className="pb-2 pr-3">{t('broadcast.successCount')}</th>
                  <th className="pb-2 pr-3">{t('broadcast.failureCount')}</th>
                  <th className="pb-2"></th>
                </tr>
              </thead>
              <tbody>
                {broadcasts.map((b) => (
                  <tr
                    key={b.id}
                    className="border-b border-white/5 hover:bg-white/[0.02] transition-colors"
                  >
                    <td className="py-2.5 pr-3">
                      <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${STATUS_STYLES[b.status] || ''}`}>
                        {getStatusLabel(b.status)}
                      </span>
                    </td>
                    <td className="py-2.5 pr-3 text-white max-w-[200px] truncate">
                      <button onClick={() => b.status !== 'draft' ? setDetailBroadcast(b) : handlePreviewDraft(b)} className="hover:text-primary-400 transition-colors text-left truncate max-w-full">
                        {b.title}
                      </button>
                    </td>
                    <td className="py-2.5 pr-3 text-gray-400">{b.exchange_filter || t('broadcast.allExchanges')}</td>
                    <td className="py-2.5 pr-3 text-gray-400">{b.total_targets}</td>
                    <td className="py-2.5 pr-3 text-gray-400 text-xs">
                      {formatDateTime(b.scheduled_at || b.completed_at || b.created_at)}
                    </td>
                    <td className="py-2.5 pr-3">
                      {b.status === 'sending' ? (
                        <BroadcastProgress
                          sent={b.sent_count}
                          failed={b.failed_count}
                          total={b.total_targets}
                          status={b.status}
                        />
                      ) : (
                        <span className="text-emerald-400">{b.sent_count}</span>
                      )}
                    </td>
                    <td className="py-2.5 pr-3">
                      <span className={b.failed_count > 0 ? 'text-red-400' : 'text-gray-600'}>
                        {b.failed_count}
                      </span>
                    </td>
                    <td className="py-2.5">
                      <div className="flex gap-1">
                        {b.status === 'draft' && (
                          <>
                            <button
                              onClick={() => handleEditDraft(b)}
                              title="Bearbeiten"
                              className="p-1 text-blue-400/60 hover:text-blue-400 transition-colors"
                            >
                              <Pencil size={14} />
                            </button>
                            <button
                              onClick={() => handlePreviewDraft(b)}
                              title={t('broadcast.preview')}
                              className="p-1 text-primary-400/60 hover:text-primary-400 transition-colors"
                            >
                              <Eye size={14} />
                            </button>
                          </>
                        )}
                        {b.status !== 'draft' && (
                          <button
                            onClick={() => setDetailBroadcast(b)}
                            title={t('broadcast.preview')}
                            className="p-1 text-gray-400/60 hover:text-white transition-colors"
                          >
                            <Eye size={14} />
                          </button>
                        )}
                        {canCancel(b.status) && (
                          <button
                            onClick={() => handleCancel(b)}
                            title={t('broadcast.cancel')}
                            className="p-1 text-yellow-400/60 hover:text-yellow-400 transition-colors"
                          >
                            <XCircle size={14} />
                          </button>
                        )}
                        {canDelete(b.status) && (
                          <button
                            onClick={() => handleDelete(b)}
                            title={t('broadcast.delete')}
                            className="p-1 text-red-400/50 hover:text-red-400 transition-colors"
                          >
                            <Trash2 size={14} />
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Mobile cards */}
          <div className="md:hidden space-y-2">
            {broadcasts.map((b) => (
              <div
                key={b.id}
                className="border border-white/10 bg-white/[0.03] rounded-xl p-3"
              >
                <div className="flex items-center justify-between mb-2">
                  <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${STATUS_STYLES[b.status] || ''}`}>
                    {getStatusLabel(b.status)}
                  </span>
                  <span className="text-[10px] text-gray-500">
                    {formatDateTime(b.scheduled_at || b.completed_at || b.created_at)}
                  </span>
                </div>
                <div className="text-sm text-white font-medium truncate mb-1">{b.title}</div>
                <div className="text-xs text-gray-500 mb-2">
                  {b.exchange_filter || t('broadcast.allExchanges')}
                </div>
                {b.status === 'sending' && (
                  <BroadcastProgress
                    sent={b.sent_count}
                    failed={b.failed_count}
                    total={b.total_targets}
                    status={b.status}
                  />
                )}
                {b.status !== 'sending' && (
                  <div className="flex gap-4 text-xs">
                    <span className="text-gray-400">
                      {t('broadcast.targets')}: {b.total_targets}
                    </span>
                    <span className="text-emerald-400">
                      {t('broadcast.successCount')}: {b.sent_count}
                    </span>
                    {b.failed_count > 0 && (
                      <span className="text-red-400">
                        {t('broadcast.failureCount')}: {b.failed_count}
                      </span>
                    )}
                  </div>
                )}
                <div className="flex gap-1 mt-2 pt-2 border-t border-white/5">
                  {b.status !== 'draft' && (
                    <button
                      onClick={() => setDetailBroadcast(b)}
                      className="p-1 text-gray-400/60 hover:text-white transition-colors text-xs flex items-center gap-1"
                    >
                      <Eye size={13} />
                      {t('broadcast.preview')}
                    </button>
                  )}
                  {canCancel(b.status) && (
                    <button
                      onClick={() => handleCancel(b)}
                      className="p-1 text-yellow-400/60 hover:text-yellow-400 transition-colors text-xs flex items-center gap-1"
                    >
                      <XCircle size={13} />
                      {t('broadcast.cancel')}
                    </button>
                  )}
                  {canDelete(b.status) && (
                    <button
                      onClick={() => handleDelete(b)}
                      className="p-1 text-red-400/50 hover:text-red-400 transition-colors text-xs flex items-center gap-1 ml-auto"
                    >
                      <Trash2 size={13} />
                      {t('broadcast.delete')}
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>

          {/* Pagination */}
          <div className="mt-4">
            <Pagination page={page} totalPages={totalPages} onPageChange={setPage} />
          </div>
        </>
      )}

      {/* Detail Modal */}
      {detailBroadcast && (
        <BroadcastDetailModal
          broadcast={detailBroadcast}
          onClose={() => setDetailBroadcast(null)}
        />
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
