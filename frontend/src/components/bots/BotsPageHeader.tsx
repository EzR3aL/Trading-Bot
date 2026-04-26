import { Plus } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { TourHelpButton } from '../ui/GuidedTour'

interface Props {
  runningCount: number
  onNewBot: () => void
  onStopAll: () => void
}

/**
 * Top-of-page header for the Bots page: title + "New Bot" CTA + optional "Stop All".
 */
export default function BotsPageHeader({ runningCount, onNewBot, onStopAll }: Props) {
  const { t } = useTranslation()

  return (
    <div className="flex items-center justify-between gap-3 mb-6">
      <h1 className="text-xl sm:text-2xl font-bold text-white tracking-tight">{t('bots.title')}</h1>
      <div className="flex items-center gap-1.5 sm:gap-2">
        <TourHelpButton tourId="bots-page" />
        <button
          onClick={onNewBot}
          aria-label={t('bots.newBot')}
          className="px-3 py-2 text-xs sm:text-sm btn-gradient inline-flex items-center justify-center gap-1.5 rounded-xl font-medium whitespace-nowrap"
          data-tour="new-bot"
        >
          <Plus size={15} />
          {t('bots.newBot')}
        </button>
        {runningCount > 1 && (
          <button
            onClick={onStopAll}
            aria-label={t('bots.stopAll')}
            className="px-3 py-2 text-xs sm:text-sm bg-red-500/10 text-red-400 rounded-xl border border-red-500/10 hover:bg-red-500/20 transition-all duration-200 font-medium inline-flex items-center justify-center whitespace-nowrap"
          >
            {t('bots.stopAll')} ({runningCount})
          </button>
        )}
      </div>
    </div>
  )
}
