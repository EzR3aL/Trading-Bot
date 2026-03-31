import { useThemeStore } from '../../stores/themeStore'

interface TooltipProps {
  active?: boolean
  payload?: Array<{ name: string; value: number; color: string }>
  label?: string
}

export default function ChartTooltip({ active, payload, label }: TooltipProps) {
  const theme = useThemeStore((s) => s.theme)
  const isLight = theme === 'light'
  if (!active || !payload?.length) return null
  return (
    <div className={`${isLight ? 'bg-white/95 border-gray-200' : 'bg-[#141a2a]/95 border-white/10'} border rounded-xl p-3 shadow-lg backdrop-blur-xl`}>
      <p className={`${isLight ? 'text-gray-500' : 'text-gray-400'} text-xs mb-1`}>{label}</p>
      {payload.map((entry, i) => (
        <p key={i} className="text-sm font-medium" style={{ color: entry.value >= 0 ? '#22c55e' : '#ef4444' }}>
          {entry.name}: ${entry.value.toFixed(2)}
        </p>
      ))}
    </div>
  )
}
