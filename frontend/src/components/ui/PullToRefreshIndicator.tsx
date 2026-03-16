import { RefreshCw } from 'lucide-react'

interface Props {
  pullDistance: number
  refreshing: boolean
  threshold?: number
}

export default function PullToRefreshIndicator({ pullDistance, refreshing, threshold = 80 }: Props) {
  const visible = pullDistance > 10 || refreshing
  if (!visible) return null

  const progress = Math.min(pullDistance / threshold, 1)
  const rotation = pullDistance * 2

  return (
    <div
      className="flex justify-center items-center overflow-hidden transition-[height] duration-200"
      style={{ height: refreshing ? 48 : pullDistance > 10 ? Math.min(pullDistance, 64) : 0 }}
    >
      <RefreshCw
        size={20}
        className={`text-primary-400 transition-transform ${refreshing ? 'animate-spin' : ''}`}
        style={!refreshing ? { transform: `rotate(${rotation}deg)`, opacity: progress } : undefined}
      />
    </div>
  )
}
