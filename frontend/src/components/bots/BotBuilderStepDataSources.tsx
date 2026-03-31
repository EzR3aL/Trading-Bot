import { useMemo } from 'react'
import { Check, LayoutGrid, List, Brain, TrendingUp, BarChart3, DollarSign, Activity, Building } from 'lucide-react'
import type { DataSource } from './BotBuilderTypes'
import { CATEGORY_ORDER } from './BotBuilderTypes'

const CATEGORY_ICONS: Record<string, typeof Brain> = {
  sentiment: Brain,
  futures: TrendingUp,
  options: BarChart3,
  spot: DollarSign,
  technical: Activity,
  tradfi: Building,
}

interface Props {
  dataSources: DataSource[]
  selectedSources: string[]
  sourcesView: 'grid' | 'list'
  onToggleSource: (id: string) => void
  onSelectAllInCategory: (category: string) => void
  onClearCategory: (category: string) => void
  onSourcesViewChange: (view: 'grid' | 'list') => void
  b: Record<string, string>
}

export default function BotBuilderStepDataSources({
  dataSources, selectedSources, sourcesView,
  onToggleSource, onSelectAllInCategory, onClearCategory, onSourcesViewChange,
  b,
}: Props) {
  // Group data sources by category
  const sourcesByCategory = useMemo(() => {
    const groups: Record<string, DataSource[]> = {}
    for (const cat of CATEGORY_ORDER) {
      const items = dataSources.filter(ds => ds.category === cat)
      if (items.length > 0) groups[cat] = items
    }
    return groups
  }, [dataSources])

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <label className="block text-sm text-gray-400">{b.dataSources}</label>
          <p className="text-xs text-gray-400 mt-0.5">
            {selectedSources.length} {b.sourcesSelected}
          </p>
        </div>
        <div className="flex items-center gap-1 bg-white/5 rounded-lg p-0.5">
          <button
            type="button"
            onClick={() => onSourcesViewChange('grid')}
            className={`p-1.5 rounded-md transition-colors ${sourcesView === 'grid' ? 'bg-white/10 text-white' : 'text-gray-500 hover:text-gray-300'}`}
            title={b.viewGrid}
          >
            <LayoutGrid size={14} />
          </button>
          <button
            type="button"
            onClick={() => onSourcesViewChange('list')}
            className={`p-1.5 rounded-md transition-colors ${sourcesView === 'list' ? 'bg-white/10 text-white' : 'text-gray-500 hover:text-gray-300'}`}
            title={b.viewList}
          >
            <List size={14} />
          </button>
        </div>
      </div>

      {CATEGORY_ORDER.map(cat => {
        const sources = sourcesByCategory[cat]
        if (!sources) return null
        const Icon = CATEGORY_ICONS[cat] || Activity
        const catLabel = b[cat] || cat
        const allSelected = sources.every(s => selectedSources.includes(s.id))

        return (
          <div key={cat}>
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <Icon size={15} className="text-gray-400" />
                <span className="text-sm font-medium text-gray-300">{catLabel}</span>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => onSelectAllInCategory(cat)}
                  className={`text-xs px-2 py-0.5 rounded ${allSelected ? 'text-gray-400' : 'text-primary-400 hover:text-primary-300'}`}
                  disabled={allSelected}
                >
                  {b.selectAll}
                </button>
                <button
                  onClick={() => onClearCategory(cat)}
                  className="text-xs px-2 py-0.5 rounded text-gray-500 hover:text-gray-400"
                >
                  {b.clearAll}
                </button>
              </div>
            </div>

            {sourcesView === 'grid' ? (
              <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2 mb-4">
                {sources.map(src => {
                  const isSelected = selectedSources.includes(src.id)
                  return (
                    <button
                      key={src.id}
                      onClick={() => onToggleSource(src.id)}
                      className={`text-left px-3 py-2.5 rounded-xl border transition-all duration-200 ${
                        isSelected
                          ? 'border-green-400/70 bg-green-950/30 shadow-[0_0_10px_rgba(74,222,128,0.1)]'
                          : 'border-white/10 bg-white/[0.03] hover:border-white/20 hover:bg-white/[0.06]'
                      }`}
                    >
                      <div className="flex items-center justify-between gap-1">
                        <span className={`text-sm font-medium ${isSelected ? 'text-green-300' : 'text-white'}`}>
                          {src.name}
                        </span>
                        <span className="text-xs text-gray-400 shrink-0">{src.provider}</span>
                      </div>
                      <div className="text-xs text-gray-400 mt-0.5 line-clamp-2">{src.description}</div>
                    </button>
                  )
                })}
              </div>
            ) : (
              <div className="space-y-1 mb-4">
                {sources.map(src => {
                  const isSelected = selectedSources.includes(src.id)
                  return (
                    <button
                      key={src.id}
                      onClick={() => onToggleSource(src.id)}
                      className={`w-full flex items-center gap-3 px-3 py-2 rounded-xl border transition-all duration-200 ${
                        isSelected
                          ? 'border-green-400/70 bg-green-950/30'
                          : 'border-white/10 bg-white/[0.03] hover:border-white/20 hover:bg-white/[0.06]'
                      }`}
                    >
                      <div className={`w-4 h-4 rounded border flex items-center justify-center shrink-0 ${
                        isSelected ? 'border-green-400 bg-green-500/20' : 'border-gray-600'
                      }`}>
                        {isSelected && <Check size={11} className="text-green-400" />}
                      </div>
                      <span className={`text-sm font-medium ${isSelected ? 'text-green-300' : 'text-white'}`}>
                        {src.name}
                      </span>
                      <span className="text-xs text-gray-400 truncate ml-auto">{src.provider}</span>
                    </button>
                  )
                })}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
