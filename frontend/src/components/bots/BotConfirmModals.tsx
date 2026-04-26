import { useTranslation } from 'react-i18next'
import ConfirmModal from '../ui/ConfirmModal'

export type BotConfirmModalState = {
  type: 'delete' | 'close-position' | 'stop' | 'hl-gate'
  id: number
  name: string
  symbol?: string
  openTrades?: number
} | null

interface Props {
  modal: BotConfirmModalState
  deletePending: boolean
  closePositionPending: boolean
  stopPending: boolean
  onDeleteConfirm: () => void
  onClosePositionConfirm: () => void
  onStopConfirm: () => void
  onHlGateConfirm: () => void
  onDismiss: () => void
}

/**
 * Renders the four confirmation modals used on the Bots page (delete / close-position /
 * stop / hl-gate). Each one is gated by `modal.type` and forwards the appropriate
 * pending flag from the parent's React Query mutations.
 */
export default function BotConfirmModals({
  modal,
  deletePending,
  closePositionPending,
  stopPending,
  onDeleteConfirm,
  onClosePositionConfirm,
  onStopConfirm,
  onHlGateConfirm,
  onDismiss,
}: Props) {
  const { t } = useTranslation()

  return (
    <>
      <ConfirmModal
        open={modal?.type === 'delete'}
        title={t('bots.deleteBot', 'Delete Bot')}
        message={t('bots.confirmDeleteMessage', { name: modal?.name })}
        confirmLabel={t('bots.delete')}
        variant="danger"
        loading={deletePending}
        onConfirm={onDeleteConfirm}
        onCancel={() => { if (!deletePending) onDismiss() }}
      />
      <ConfirmModal
        open={modal?.type === 'close-position'}
        title={t('bots.closePosition', 'Close Position')}
        message={t('bots.closePositionConfirm', { symbol: modal?.symbol })}
        confirmLabel={t('bots.closePosition', 'Close Position')}
        variant="warning"
        loading={closePositionPending}
        onConfirm={onClosePositionConfirm}
        onCancel={() => { if (!closePositionPending) onDismiss() }}
      />
      <ConfirmModal
        open={modal?.type === 'stop'}
        title={t('bots.stopBot', 'Stop Bot')}
        message={
          (modal?.openTrades ?? 0) > 0
            ? t('bots.confirmStopMessageWithOpen', {
                name: modal?.name,
                count: modal?.openTrades,
                defaultValue: 'Stop "{{name}}"? It currently has {{count}} open position(s) that will NOT be closed automatically.',
              })
            : t('bots.confirmStopMessage', {
                name: modal?.name,
                defaultValue: 'Stop "{{name}}"? The bot will stop trading.',
              })
        }
        confirmLabel={t('bots.stop')}
        variant={(modal?.openTrades ?? 0) > 0 ? 'warning' : 'danger'}
        loading={stopPending}
        onConfirm={onStopConfirm}
        onCancel={() => { if (!stopPending) onDismiss() }}
      />
      <ConfirmModal
        open={modal?.type === 'hl-gate'}
        title={t('hlSetup.setupRequiredTitle', 'Hyperliquid Setup Required')}
        message={t('hlSetup.setupRequiredMessage', {
          defaultValue: 'This bot requires Hyperliquid builder fee approval and referral verification before it can be started. Please complete the setup in Settings first.',
        })}
        confirmLabel={t('hlSetup.goToSettings', 'Go to Settings')}
        cancelLabel={t('common.cancel', 'Cancel')}
        variant="info"
        onConfirm={onHlGateConfirm}
        onCancel={onDismiss}
      />
    </>
  )
}
