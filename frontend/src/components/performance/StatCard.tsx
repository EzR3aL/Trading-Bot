import { ArrowDownRight, ArrowUpRight } from 'lucide-react'

interface Props {
  label: string
  value: string
  color?: string
  isPositive?: boolean | null
}

/**
 * Small summary stat tile used in the BotPerformance detail panel.
 */
export default function StatCard({ label, value, color, isPositive }: Props) {
  return (
    <div className="bg-white/5 rounded-xl p-3 border border-white/5 text-center">
      <div className="text-[10px] text-gray-400 mb-1 uppercase tracking-wider font-medium">{label}</div>
      <div className={`text-lg font-bold flex items-center justify-center gap-1 ${color || 'text-white'}`}>
        {value}
        {isPositive === true && <ArrowUpRight size={16} className="text-profit" />}
        {isPositive === false && <ArrowDownRight size={16} className="text-loss" />}
      </div>
    </div>
  )
}
