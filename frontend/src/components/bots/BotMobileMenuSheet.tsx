import { Copy, Pencil, Trash2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { BotStatus } from './types'

interface Props {
  open: boolean
  bot: BotStatus | null
  onClose: () => void
  onEdit: (id: number) => void
  onDuplicate: (id: number) => void
  onDelete: (id: number, name: string) => void
}

/**
 * Mobile bottom-sheet menu for the per-bot 3-dot actions (Edit / Duplicate / Delete).
 * Mirrors the "Mehr" nav animation: translate-y-0 when open, translate-y-full when closed.
 */
export default function BotMobileMenuSheet({ open, bot, onClose, onEdit, onDuplicate, onDelete }: Props) {
  const { t } = useTranslation()

  return (
    <div
      className={`fixed bottom-0 left-0 right-0 z-[9999] bg-[#0f1420] border-t border-white/10 rounded-t-2xl transition-transform duration-300 ease-out ${
        open ? 'translate-y-0' : 'translate-y-full'
      }`}
    >
      {bot && (
        <>
          <div className="flex justify-center pt-3 pb-1">
            <div className="w-10 h-1 rounded-full bg-white/20" />
          </div>
          <p className="text-white/60 text-sm font-medium text-center pb-2">{bot.name}</p>
          <div className="px-4 pb-8">
            <button
              onClick={() => { onClose(); onEdit(bot.bot_config_id) }}
              disabled={bot.status === 'running'}
              className="w-full flex items-center gap-3 px-4 py-3.5 text-base text-gray-200 hover:bg-white/5 active:bg-white/10 disabled:opacity-30 transition-colors rounded-xl"
            >
              <Pencil size={18} />
              {t('bots.edit')}
            </button>
            <button
              onClick={() => { onClose(); onDuplicate(bot.bot_config_id) }}
              className="w-full flex items-center gap-3 px-4 py-3.5 text-base text-gray-200 hover:bg-white/5 active:bg-white/10 transition-colors rounded-xl"
            >
              <Copy size={18} />
              {t('bots.duplicate')}
            </button>
            <div className="border-t border-white/5 my-1" />
            <button
              onClick={() => { onClose(); onDelete(bot.bot_config_id, bot.name) }}
              disabled={bot.status === 'running'}
              className="w-full flex items-center gap-3 px-4 py-3.5 text-base text-red-400 hover:bg-red-500/5 active:bg-red-500/10 disabled:opacity-30 transition-colors rounded-xl"
            >
              <Trash2 size={18} />
              {t('bots.delete')}
            </button>
          </div>
        </>
      )}
    </div>
  )
}
