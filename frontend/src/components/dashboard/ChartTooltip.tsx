interface TooltipProps {
  active?: boolean
  payload?: Array<{ name: string; value: number; color: string }>
  label?: string
}

export default function ChartTooltip({ active, payload, label }: TooltipProps) {
  if (!active || !payload?.length) return null
  return (
    <div className="bg-[#141a2a]/95 border border-white/10 rounded-xl p-3 shadow-lg backdrop-blur-xl">
      <p className="text-gray-400 text-xs mb-1">{label}</p>
      {payload.map((entry, i) => (
        <p key={i} className="text-sm font-medium" style={{ color: entry.value >= 0 ? '#22c55e' : '#ef4444' }}>
          {entry.name}: ${entry.value.toFixed(2)}
        </p>
      ))}
    </div>
  )
}
