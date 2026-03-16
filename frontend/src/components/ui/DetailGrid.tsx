import { memo } from 'react'

export interface DetailItem {
  label: string
  value: React.ReactNode
  colSpan?: 2
  hidden?: boolean
}

/**
 * Shared 2-column detail grid for expandable mobile cards.
 * Consistent styling: gray-400 labels, gray-200 values, 9px uppercase labels.
 */
function DetailGridInner({ items }: { items: DetailItem[] }) {
  return (
    <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-[11px]">
      {items
        .filter((d) => !d.hidden)
        .map((d, i) => (
          <div key={i} className={d.colSpan === 2 ? 'col-span-2' : ''}>
            <span className="text-gray-400 block text-[9px] uppercase tracking-wider">{d.label}</span>
            <span className="text-gray-200">{d.value}</span>
          </div>
        ))}
    </div>
  )
}

export const DetailGrid = memo(DetailGridInner)
