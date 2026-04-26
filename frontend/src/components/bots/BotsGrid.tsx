import { Activity, Plus } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { SkeletonBotCard } from '../ui/Skeleton'
import BotCard from './BotCard'
import type { BotStatus } from './types'

interface Props {
  loading: boolean
  bots: BotStatus[]
  isMobile: boolean
  isAdmin: boolean
  expandedBotId: number | null
  actionLoading: number | null
  closePositionOpen: number | null
  moreMenuOpen: number | null
  onNewBot: () => void
  onToggleExpand: (id: number) => void
  onStart: (id: number) => void
  onStopClick: (id: number) => void
  onClosePosition: (botId: number, symbol: string) => void
  onSetClosePositionOpen: (id: number | null) => void
  onShowHistory: (bot: BotStatus) => void
  onSetMoreMenuOpen: (id: number | null) => void
  onEdit: (id: number) => void
  onDuplicate: (id: number) => void
  onDelete: (id: number, name: string) => void
}

/**
 * Renders the loading skeleton, empty state, or grid of BotCards depending on `loading`/`bots`.
 */
export default function BotsGrid({
  loading,
  bots,
  isMobile,
  isAdmin,
  expandedBotId,
  actionLoading,
  closePositionOpen,
  moreMenuOpen,
  onNewBot,
  onToggleExpand,
  onStart,
  onStopClick,
  onClosePosition,
  onSetClosePositionOpen,
  onShowHistory,
  onSetMoreMenuOpen,
  onEdit,
  onDuplicate,
  onDelete,
}: Props) {
  const { t } = useTranslation()

  if (loading) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {Array.from({ length: 3 }).map((_, i) => (
          <SkeletonBotCard key={i} />
        ))}
      </div>
    )
  }

  if (bots.length === 0) {
    return (
      <div className="glass-card rounded-xl text-center py-16">
        <Activity className="mx-auto mb-4 text-gray-600 dark:text-gray-600" size={48} />
        <p className="text-gray-500 dark:text-gray-400 font-medium">{t('bots.noBots')}</p>
        <p className="text-gray-400 dark:text-gray-500 text-sm mt-1">{t('bots.noBotsHint')}</p>
        <button
          onClick={onNewBot}
          className="mt-4 inline-flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-primary-600 to-primary-500 text-white text-sm font-medium rounded-xl shadow-glow-sm hover:shadow-glow transition-all duration-200"
        >
          <Plus size={16} />
          {t('bots.noBotsAction')}
        </button>
      </div>
    )
  }

  return (
    <div className={isMobile ? 'space-y-2' : 'grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4'}>
      {bots.map((bot, index) => (
        <BotCard
          key={bot.bot_config_id}
          bot={bot}
          isFirst={index === 0}
          isMobile={isMobile}
          isAdmin={isAdmin}
          isExpanded={expandedBotId === bot.bot_config_id}
          actionLoading={actionLoading}
          closePositionOpen={closePositionOpen}
          moreMenuOpen={moreMenuOpen}
          onToggleExpand={() => onToggleExpand(bot.bot_config_id)}
          onStart={onStart}
          onStopClick={onStopClick}
          onClosePosition={onClosePosition}
          onSetClosePositionOpen={onSetClosePositionOpen}
          onShowHistory={onShowHistory}
          onSetMoreMenuOpen={onSetMoreMenuOpen}
          onEdit={onEdit}
          onDuplicate={onDuplicate}
          onDelete={onDelete}
        />
      ))}
    </div>
  )
}
