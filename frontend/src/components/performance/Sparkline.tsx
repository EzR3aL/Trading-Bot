interface Props {
  data: number[]
  color: string
  width?: number
  height?: number
}

/**
 * Lightweight inline-SVG sparkline (no recharts dependency) used in the BotCard.
 */
export default function Sparkline({ data, color, width = 80, height = 32 }: Props) {
  if (data.length < 2) return <div style={{ width, height }} />

  const min = Math.min(...data)
  const max = Math.max(...data)
  const range = max - min || 1
  const pad = 2

  const points = data.map((v, i) => {
    const x = pad + (i / (data.length - 1)) * (width - pad * 2)
    const y = pad + (1 - (v - min) / range) * (height - pad * 2)
    return `${x},${y}`
  })

  const linePath = points.join(' ')
  const areaPath = `${points.join(' ')} ${width - pad},${height} ${pad},${height}`

  const gradientId = `spark-${color.replace('#', '')}`

  return (
    <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" className="w-full overflow-visible" style={{ height }}>
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity={0.3} />
          <stop offset="100%" stopColor={color} stopOpacity={0} />
        </linearGradient>
      </defs>
      <polygon points={areaPath} fill={`url(#${gradientId})`} />
      <polyline points={linePath} fill="none" stroke={color} strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}
