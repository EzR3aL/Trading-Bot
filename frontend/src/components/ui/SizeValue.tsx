import { ArrowLeftRight } from 'lucide-react'
import { useSizeUnitStore, formatSize } from '../../stores/sizeUnitStore'

interface SizeValueProps {
  size: number
  price: number
  symbol: string
  compact?: boolean
}

export default function SizeValue({ size, price, symbol, compact }: SizeValueProps) {
  const { unit, toggle } = useSizeUnitStore()

  return (
    <button
      type="button"
      onClick={(e) => { e.stopPropagation(); toggle() }}
      className="inline-flex items-center gap-1 tabular-nums hover:text-white transition-colors group"
      title={unit === 'token' ? 'Show USDT value' : 'Show token size'}
    >
      {formatSize(size, price, unit, symbol)}
      {!compact && (
        <ArrowLeftRight
          size={10}
          className="text-gray-600 group-hover:text-gray-400 transition-colors shrink-0"
        />
      )}
    </button>
  )
}
