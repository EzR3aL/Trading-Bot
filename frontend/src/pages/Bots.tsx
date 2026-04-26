import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  useBots as useBotsQuery,
  useStartBot,
  useStopBot,
  useDeleteBot,
  useDuplicateBot,
  useStopAllBots,
  useClosePosition,
} from '../api/queries'
import { getApiErrorMessage } from '../utils/api-error'
import { useFilterStore } from '../stores/filterStore'
import { useToastStore } from '../stores/toastStore'
import BotBuilder from '../components/bots/BotBuilder'
import GuidedTour from '../components/ui/GuidedTour'
import useIsMobile from '../hooks/useIsMobile'
import useHaptic from '../hooks/useHaptic'
import usePullToRefresh from '../hooks/usePullToRefresh'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
import { useAuthStore } from '../stores/authStore'
import PullToRefreshIndicator from '../components/ui/PullToRefreshIndicator'
import BotsGrid from '../components/bots/BotsGrid'
import BotTradeHistoryModal from '../components/bots/BotTradeHistoryModal'
import BotMobileMenuSheet from '../components/bots/BotMobileMenuSheet'
import BotConfirmModals, { type BotConfirmModalState } from '../components/bots/BotConfirmModals'
import BotsPageHeader from '../components/bots/BotsPageHeader'
import { botsTourSteps } from '../components/bots/botsTourSteps'
import type { BotStatus } from '../components/bots/types'

export default function Bots() {
  const { t } = useTranslation()
  useDocumentTitle(t('nav.myBots'))
  const navigate = useNavigate()
  const { demoFilter } = useFilterStore()
  const isMobile = useIsMobile()
  const haptic = useHaptic()
  const { addToast } = useToastStore()
  const isAdmin = useAuthStore((s) => s.user?.role === 'admin')

  const handleStartError = (err: unknown) => {
    const detail = (err as any)?.response?.data?.detail
    if (detail && typeof detail === 'object' && detail.message) {
      const msg = detail.affiliate_url
        ? `${detail.message}\n${detail.affiliate_url}`
        : detail.message
      addToast('error', msg, 10000)
    } else {
      addToast('error', getApiErrorMessage(err, t('bots.failedStart')))
    }
  }
  // Bot list via React Query (polls every 5s, matching original setInterval)
  const { data: botsData, isLoading: loading, error: botsError, refetch: refetchBots } = useBotsQuery(demoFilter)
  const bots: BotStatus[] = (botsData?.bots as BotStatus[]) || []
  const error = botsError ? t('common.error') : ''

  const [showBuilder, setShowBuilder] = useState(false)
  const [editBotId, setEditBotId] = useState<number | null>(null)
  const [expandedBotId, setExpandedBotId] = useState<number | null>(null)
  const [actionLoading, setActionLoading] = useState<number | null>(null)
  const [historyBot, setHistoryBot] = useState<BotStatus | null>(null)
  const [moreMenuOpen, setMoreMenuOpen] = useState<number | null>(null)
  const [closePositionOpen, setClosePositionOpen] = useState<number | null>(null)
  const [confirmModal, setConfirmModal] = useState<BotConfirmModalState>(null)

  const startBot = useStartBot()
  const stopBot = useStopBot()
  const deleteBot = useDeleteBot()
  const duplicateBot = useDuplicateBot()
  const stopAllBots = useStopAllBots()
  const closePosition = useClosePosition()

  const { containerRef, refreshing, pullDistance } = usePullToRefresh({
    onRefresh: async () => { await refetchBots() },
    disabled: !isMobile,
  })

  const handleStart = async (id: number) => {
    haptic.medium()
    // Check if HL bot needs builder fee approval or referral first (admins bypass).
    // Show a blocking modal instead of a dismissible toast so users cannot miss the requirement.
    const bot = bots.find(b => b.bot_config_id === id)
    if (!isAdmin && bot?.exchange_type === 'hyperliquid' && (bot?.builder_fee_approved === false || bot?.referral_verified === false)) {
      setConfirmModal({ type: 'hl-gate', id, name: bot?.name || '' })
      return
    }

    setActionLoading(id)
    try {
      await startBot.mutateAsync(id)
      addToast('success', t('bots.start'))
    } catch (err) {
      handleStartError(err)
    }
    setActionLoading(null)
  }

  const handleStopClick = (id: number) => {
    haptic.heavy()
    const bot = bots.find(b => b.bot_config_id === id)
    setConfirmModal({
      type: 'stop',
      id,
      name: bot?.name || '',
      openTrades: bot?.open_trades ?? 0,
    })
  }

  const confirmStop = async () => {
    if (!confirmModal || confirmModal.type !== 'stop') return
    const id = confirmModal.id
    setActionLoading(id)
    try {
      await stopBot.mutateAsync(id)
      addToast('info', t('bots.stop'))
      setConfirmModal(null)
    } catch (err) {
      addToast('error', getApiErrorMessage(err, t('bots.failedStop')))
      setConfirmModal(null)
    }
    setActionLoading(null)
  }

  const handleDelete = async (id: number, name: string) => {
    haptic.error()
    setConfirmModal({ type: 'delete', id, name })
  }

  const confirmDelete = async () => {
    if (!confirmModal) return
    try {
      await deleteBot.mutateAsync(confirmModal.id)
      addToast('success', t('bots.deleted', { name: confirmModal.name }))
    } catch (err) {
      addToast('error', getApiErrorMessage(err, t('bots.failedDelete')))
    }
    setConfirmModal(null)
  }

  const handleDuplicate = async (id: number) => {
    haptic.light()
    try {
      await duplicateBot.mutateAsync(id)
      addToast('success', t('bots.duplicated'))
    } catch (err) {
      addToast('error', getApiErrorMessage(err, t('bots.failedDuplicate')))
    }
  }

  const handleClosePosition = async (botId: number, symbol: string) => {
    haptic.heavy()
    setConfirmModal({ type: 'close-position', id: botId, name: '', symbol })
  }

  const confirmClosePosition = async () => {
    if (!confirmModal || confirmModal.type !== 'close-position') return
    setActionLoading(confirmModal.id)
    try {
      await closePosition.mutateAsync({ botId: confirmModal.id, symbol: confirmModal.symbol! })
      addToast('success', t('bots.positionClosed', { symbol: confirmModal.symbol }))
    } catch (err) {
      addToast('error', getApiErrorMessage(err, t('bots.failedClosePosition')))
    }
    setActionLoading(null)
    setConfirmModal(null)
  }

  const handleStopAll = async () => {
    try {
      await stopAllBots.mutateAsync()
      addToast('info', t('bots.stopAll'))
    } catch {
      addToast('error', t('common.error'))
    }
  }

  const handleBuilderDone = () => {
    setShowBuilder(false)
    setEditBotId(null)
    refetchBots()
  }

  const runningCount = bots.filter(b => b.status === 'running').length

  if (showBuilder || editBotId !== null) {
    return (
      <BotBuilder
        botId={editBotId}
        onDone={handleBuilderDone}
        onCancel={() => { setShowBuilder(false); setEditBotId(null) }}
      />
    )
  }

  const menuBot = moreMenuOpen !== null ? bots.find(b => b.bot_config_id === moreMenuOpen) ?? null : null

  return (
    <div ref={containerRef} style={{ overscrollBehavior: 'contain' }} className="animate-in" aria-busy={loading}>
      <PullToRefreshIndicator pullDistance={pullDistance} refreshing={refreshing} />

      <BotsPageHeader runningCount={runningCount} onNewBot={() => setShowBuilder(true)} onStopAll={handleStopAll} />

      {/* Error */}
      {error && (
        <div role="alert" className="mb-4 p-3 bg-red-500/10 border border-red-500/20 rounded-xl text-red-400 text-sm">
          {error}
        </div>
      )}

      <BotsGrid
        loading={loading}
        bots={bots}
        isMobile={isMobile}
        isAdmin={isAdmin}
        expandedBotId={expandedBotId}
        actionLoading={actionLoading}
        closePositionOpen={closePositionOpen}
        moreMenuOpen={moreMenuOpen}
        onNewBot={() => setShowBuilder(true)}
        onToggleExpand={(id) => setExpandedBotId(expandedBotId === id ? null : id)}
        onStart={handleStart}
        onStopClick={handleStopClick}
        onClosePosition={handleClosePosition}
        onSetClosePositionOpen={setClosePositionOpen}
        onShowHistory={setHistoryBot}
        onSetMoreMenuOpen={setMoreMenuOpen}
        onEdit={setEditBotId}
        onDuplicate={handleDuplicate}
        onDelete={handleDelete}
      />

      {/* Trade History Modal */}
      {historyBot && (
        <BotTradeHistoryModal bot={historyBot} onClose={() => setHistoryBot(null)} t={t} />
      )}

      {/* Mobile bottom sheet overlay for 3-dot menu */}
      {isMobile && moreMenuOpen !== null && (
        <button
          type="button"
          aria-label={t('common.close')}
          onClick={() => setMoreMenuOpen(null)}
          className="fixed inset-0 z-[9998] w-full h-full bg-black/60 backdrop-blur-sm border-0 appearance-none cursor-default"
        />
      )}
      {/* Desktop overlay (transparent click-catcher) */}
      {!isMobile && moreMenuOpen !== null && (
        <button
          type="button"
          aria-label={t('common.close')}
          tabIndex={-1}
          onClick={() => setMoreMenuOpen(null)}
          className="fixed inset-0 z-20 w-full h-full bg-transparent border-0 appearance-none cursor-default"
        />
      )}

      {/* Mobile bottom sheet menu (matches "Mehr" nav animation) */}
      {isMobile && (
        <BotMobileMenuSheet
          open={moreMenuOpen !== null}
          bot={menuBot}
          onClose={() => setMoreMenuOpen(null)}
          onEdit={setEditBotId}
          onDuplicate={handleDuplicate}
          onDelete={handleDelete}
        />
      )}

      {/* Guided Tour */}
      <GuidedTour
        tourId="bots-page"
        steps={botsTourSteps}
        autoStart={!loading && !showBuilder && !editBotId}
      />

      {/* Confirmation Modals */}
      <BotConfirmModals
        modal={confirmModal}
        deletePending={deleteBot.isPending}
        closePositionPending={closePosition.isPending}
        stopPending={stopBot.isPending}
        onDeleteConfirm={confirmDelete}
        onClosePositionConfirm={confirmClosePosition}
        onStopConfirm={confirmStop}
        onHlGateConfirm={() => {
          setConfirmModal(null)
          navigate('/settings')
        }}
        onDismiss={() => setConfirmModal(null)}
      />
    </div>
  )
}
