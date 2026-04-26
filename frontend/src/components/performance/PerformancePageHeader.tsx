import { useTranslation } from 'react-i18next'
import { BarChart3, LayoutGrid } from 'lucide-react'

interface Props {
  viewMode: 'cards' | 'grid'
  days: number
  onViewModeChange: (mode: 'cards' | 'grid') => void
  onDaysChange: (days: number) => void
}

/**
 * Header bar for the BotPerformance page: title + cards/grid view toggle + days range pills.
 */
export default function PerformancePageHeader({ viewMode, days, onViewModeChange, onDaysChange }: Props) {
  const { t } = useTranslation()

  return (
    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-6">
      <h1 className="text-2xl font-bold text-white tracking-tight">{t('performance.title')}</h1>
      <div className="flex items-center gap-3">
        {/* View Toggle */}
        <div className="flex gap-0.5 bg-white/5 rounded-lg p-0.5 border border-white/5">
          <button
            onClick={() => onViewModeChange('cards')}
            aria-label="Cards view"
            className={`p-1.5 rounded-md transition-all duration-200 ${
              viewMode === 'cards'
                ? 'bg-white/10 text-white'
                : 'text-gray-500 hover:text-gray-300'
            }`}
          >
            <BarChart3 size={14} />
          </button>
          <button
            onClick={() => onViewModeChange('grid')}
            aria-label="Grid view"
            className={`p-1.5 rounded-md transition-all duration-200 ${
              viewMode === 'grid'
                ? 'bg-white/10 text-white'
                : 'text-gray-500 hover:text-gray-300'
            }`}
          >
            <LayoutGrid size={14} />
          </button>
        </div>
        <div className="flex gap-1 bg-white/5 rounded-xl p-0.5 border border-white/5">
          {[7, 14, 30, 90].map((d) => (
            <button
              key={d}
              onClick={() => onDaysChange(d)}
              aria-label={`${d} days period`}
              className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-all duration-200 ${
                days === d
                  ? 'bg-gradient-to-r from-primary-600 to-primary-500 text-white shadow-glow-sm'
                  : 'text-gray-400 hover:text-white hover:bg-white/5'
              }`}
            >
              {d}d
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
