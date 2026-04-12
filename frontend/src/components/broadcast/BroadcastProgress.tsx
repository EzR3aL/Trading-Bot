import { useTranslation } from 'react-i18next'

interface BroadcastProgressProps {
  sent: number
  failed: number
  total: number
  status: string
}

export default function BroadcastProgress({ sent, failed, total, status }: BroadcastProgressProps) {
  const { t } = useTranslation()
  const sentPercent = total > 0 ? (sent / total) * 100 : 0
  const failedPercent = total > 0 ? (failed / total) * 100 : 0

  return (
    <div className="w-full">
      <div
        className={`relative h-2 rounded-full bg-white/5 overflow-hidden ${
          status === 'sending' ? 'animate-pulse' : ''
        }`}
      >
        <div
          className="absolute left-0 top-0 h-full bg-emerald-500 transition-all duration-500"
          style={{ width: `${sentPercent}%` }}
        />
        <div
          className="absolute top-0 h-full bg-red-500 transition-all duration-500"
          style={{ left: `${sentPercent}%`, width: `${failedPercent}%` }}
        />
      </div>
      <div className="text-[11px] text-gray-400 mt-1">
        {t('broadcast.progress', { sent, total })}
        {failed > 0 && (
          <span className="text-red-400 ml-1">
            ({failed} {t('broadcast.statusFailed').toLowerCase()})
          </span>
        )}
      </div>
    </div>
  )
}
