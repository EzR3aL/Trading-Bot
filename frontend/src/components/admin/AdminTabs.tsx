import { useTranslation } from 'react-i18next'
import { TABS, type TabKey } from './types'

interface Props {
  activeTab: TabKey
  onChange: (tab: TabKey) => void
}

/**
 * Tab navigation row for the Admin page. Renders the TABS list as horizontally
 * scrollable pills.
 */
export default function AdminTabs({ activeTab, onChange }: Props) {
  const { t } = useTranslation()
  return (
    <div className="flex gap-1 mb-6 bg-gray-900 p-1 rounded-lg w-fit overflow-x-auto max-w-full">
      {TABS.map((tab) => (
        <button
          key={tab.key}
          onClick={() => onChange(tab.key)}
          className={`px-2 sm:px-4 py-2 text-xs sm:text-sm rounded whitespace-nowrap ${
            activeTab === tab.key
              ? 'bg-primary-600 text-white'
              : 'text-gray-400 hover:text-white'
          }`}
        >
          {t(tab.labelKey)}
        </button>
      ))}
    </div>
  )
}
