/* ── Skeleton Loader Components ─────────────────────────── */

const SKELETON_BAR_HEIGHTS = [62, 34, 78, 45, 23, 56, 41, 69, 52, 37, 74, 28, 63, 48, 31, 71, 44, 59, 26, 67]

function SkeletonBase({ className = '', style }: { className?: string; style?: React.CSSProperties }) {
  return (
    <div className={`skeleton-pulse rounded-lg bg-white/5 ${className}`} style={style} />
  )
}

export function SkeletonCard() {
  return (
    <div className="glass-card rounded-xl p-4 space-y-3">
      <SkeletonBase className="h-4 w-24" />
      <SkeletonBase className="h-8 w-32" />
      <SkeletonBase className="h-3 w-40" />
    </div>
  )
}

export function SkeletonChart({ height = 'h-[250px]' }: { height?: string }) {
  return (
    <div className={`glass-card rounded-xl p-5 ${height}`}>
      <SkeletonBase className="h-4 w-32 mb-4" />
      <div className="flex items-end gap-1 h-[calc(100%-2rem)]">
        {Array.from({ length: 20 }).map((_, i) => (
          <SkeletonBase
            key={i}
            className="flex-1"
            style={{ height: `${SKELETON_BAR_HEIGHTS[i]}%` } as React.CSSProperties}
          />
        ))}
      </div>
    </div>
  )
}

export function SkeletonTable({ rows = 5, cols = 6 }: { rows?: number; cols?: number }) {
  return (
    <div className="glass-card rounded-xl overflow-hidden">
      {/* Header */}
      <div className="flex gap-4 p-4 border-b border-white/5">
        {Array.from({ length: cols }).map((_, i) => (
          <SkeletonBase key={i} className="h-4 flex-1" />
        ))}
      </div>
      {/* Rows */}
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex gap-4 p-4 border-b border-white/5 last:border-0">
          {Array.from({ length: cols }).map((_, j) => (
            <SkeletonBase key={j} className="h-4 flex-1" />
          ))}
        </div>
      ))}
    </div>
  )
}

export function SkeletonBotCard() {
  return (
    <div className="glass-card rounded-xl p-5 space-y-4">
      <div className="flex items-start justify-between">
        <div className="space-y-2">
          <SkeletonBase className="h-5 w-28" />
          <div className="flex gap-2">
            <SkeletonBase className="h-5 w-16" />
            <SkeletonBase className="h-5 w-12" />
          </div>
        </div>
        <SkeletonBase className="h-5 w-16" />
      </div>
      <div className="flex gap-2">
        <SkeletonBase className="h-5 w-14" />
        <SkeletonBase className="h-5 w-14" />
      </div>
      <div className="grid grid-cols-3 gap-3">
        <div className="space-y-1">
          <SkeletonBase className="h-3 w-12 mx-auto" />
          <SkeletonBase className="h-5 w-16 mx-auto" />
        </div>
        <div className="space-y-1">
          <SkeletonBase className="h-3 w-12 mx-auto" />
          <SkeletonBase className="h-5 w-10 mx-auto" />
        </div>
        <div className="space-y-1">
          <SkeletonBase className="h-3 w-12 mx-auto" />
          <SkeletonBase className="h-5 w-10 mx-auto" />
        </div>
      </div>
      <div className="flex gap-2 pt-2 border-t border-white/5">
        <SkeletonBase className="h-8 flex-1" />
        <SkeletonBase className="h-8 w-8" />
        <SkeletonBase className="h-8 w-8" />
      </div>
    </div>
  )
}

export function DashboardSkeleton() {
  return (
    <div className="space-y-6 animate-in">
      {/* Header */}
      <div className="flex items-center justify-between">
        <SkeletonBase className="h-8 w-40" />
        <div className="flex gap-1">
          {Array.from({ length: 4 }).map((_, i) => (
            <SkeletonBase key={i} className="h-9 w-16" />
          ))}
        </div>
      </div>
      {/* Stat cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <SkeletonCard key={i} />
        ))}
      </div>
      {/* Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2">
          <SkeletonChart />
        </div>
        <SkeletonChart />
      </div>
      {/* Table */}
      <SkeletonTable rows={5} cols={8} />
    </div>
  )
}
