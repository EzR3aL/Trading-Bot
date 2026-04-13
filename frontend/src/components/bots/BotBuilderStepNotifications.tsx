import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Check, CheckCircle, ChevronDown, Bell, Plus, X } from 'lucide-react'

interface PnlAlertSettings {
  enabled: boolean
  mode: 'dollar' | 'percent'
  thresholds: number[]
  direction: 'profit' | 'loss' | 'both'
}

interface Props {
  discordWebhookUrl: string
  telegramBotToken: string
  telegramChatId: string
  openNotif: string | null
  discordConfigured: boolean
  telegramConfigured: boolean
  pnlAlertSettings: PnlAlertSettings
  onDiscordWebhookUrlChange: (val: string) => void
  onTelegramBotTokenChange: (val: string) => void
  onTelegramChatIdChange: (val: string) => void
  onOpenNotifChange: (val: string | null) => void
  onPnlAlertSettingsChange: (val: PnlAlertSettings) => void
  onTestDiscord?: () => void
  onTestTelegram?: () => void
}

function ThresholdChipInput({
  thresholds, unit, step, onChange,
}: {
  thresholds: number[]
  unit: string
  step: number
  onChange: (vals: number[]) => void
}) {
  const [input, setInput] = useState('')

  const addThreshold = () => {
    const val = parseFloat(input)
    if (isNaN(val) || val <= 0 || val > 10000) return
    if (thresholds.includes(val)) { setInput(''); return }
    if (thresholds.length >= 10) return
    onChange([...thresholds, val].sort((a, b) => a - b))
    setInput('')
  }

  const removeThreshold = (val: number) => {
    onChange(thresholds.filter((t) => t !== val))
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') { e.preventDefault(); addThreshold() }
  }

  return (
    <div>
      <label className="block text-xs text-gray-400 mb-2">Schwellenwerte</label>

      {/* Existing chips */}
      {thresholds.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-2">
          {thresholds.map((val) => (
            <span
              key={val}
              className="inline-flex items-center gap-1 px-2 py-1 rounded-md bg-amber-500/15 border border-amber-500/25 text-amber-300 text-xs font-medium"
            >
              {unit === '$' ? `$${val}` : `${val}%`}
              <button
                type="button"
                onClick={() => removeThreshold(val)}
                className="hover:text-white transition-colors"
              >
                <X size={12} />
              </button>
            </span>
          ))}
        </div>
      )}

      {/* Add input */}
      {thresholds.length < 10 && (
        <div className="flex items-center gap-2">
          <div className="relative w-32">
            <input
              type="number"
              min="0.1"
              max="10000"
              step={step}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={unit === '%' ? '5' : '100'}
              className="filter-select w-full text-sm pr-7"
            />
            <span className="absolute right-2.5 top-1/2 -translate-y-1/2 text-xs text-gray-500 pointer-events-none">
              {unit}
            </span>
          </div>
          <button
            type="button"
            onClick={addThreshold}
            disabled={!input}
            className="p-1.5 rounded-lg bg-amber-500/15 border border-amber-500/25 text-amber-400 hover:bg-amber-500/25 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
          >
            <Plus size={16} />
          </button>
        </div>
      )}

      <p className="text-[10px] text-gray-500 mt-1.5">
        Wert eingeben und Enter drücken. Maximal 10 Schwellenwerte.
      </p>
    </div>
  )
}

export default function BotBuilderStepNotifications({
  discordWebhookUrl, telegramBotToken, telegramChatId, openNotif,
  discordConfigured, telegramConfigured, pnlAlertSettings,
  onDiscordWebhookUrlChange, onTelegramBotTokenChange, onTelegramChatIdChange,
  onOpenNotifChange, onPnlAlertSettingsChange, onTestDiscord, onTestTelegram,
}: Props) {
  const { t } = useTranslation()

  const updateAlert = (patch: Partial<PnlAlertSettings>) => {
    // Clear thresholds when switching mode — percent values don't make sense as dollars and vice versa
    if (patch.mode && patch.mode !== pnlAlertSettings.mode) {
      patch.thresholds = []
    }
    onPnlAlertSettingsChange({ ...pnlAlertSettings, ...patch })
  }

  return (
    <div className="space-y-6">
      <div>
        <label className="block text-sm text-gray-300 mb-3">{t('settings.notifications')}</label>
        <div className="space-y-2">

        {/* Discord */}
        <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] overflow-hidden">
          <button
            type="button"
            onClick={() => onOpenNotifChange(openNotif === 'discord' ? null : 'discord')}
            className="w-full flex items-center gap-3 p-3.5 hover:bg-white/[0.02] transition-colors"
          >
            <svg viewBox="0 0 24 24" className="w-5 h-5 shrink-0" fill="#5865F2"><path d="M20.317 4.37a19.791 19.791 0 0 0-4.885-1.515.074.074 0 0 0-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 0 0-5.487 0 12.64 12.64 0 0 0-.617-1.25.077.077 0 0 0-.079-.037A19.736 19.736 0 0 0 3.677 4.37a.07.07 0 0 0-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 0 0 .031.057 19.9 19.9 0 0 0 5.993 3.03.078.078 0 0 0 .084-.028c.462-.63.874-1.295 1.226-1.994a.076.076 0 0 0-.041-.106 13.107 13.107 0 0 1-1.872-.892.077.077 0 0 1-.008-.128 10.2 10.2 0 0 0 .372-.292.074.074 0 0 1 .077-.01c3.928 1.793 8.18 1.793 12.062 0a.074.074 0 0 1 .078.01c.12.098.246.198.373.292a.077.077 0 0 1-.006.127 12.299 12.299 0 0 1-1.873.892.077.077 0 0 0-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 0 0 .084.028 19.839 19.839 0 0 0 6.002-3.03.077.077 0 0 0 .032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 0 0-.031-.03zM8.02 15.33c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.956-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.956 2.418-2.157 2.418zm7.975 0c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.955-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.946 2.418-2.157 2.418z"/></svg>
            <span className="text-sm font-medium text-white">Discord</span>
            {(discordWebhookUrl || discordConfigured) ? (
              <span className="flex items-center gap-1 text-[10px] text-emerald-400 font-medium"><Check size={12} /> aktiv</span>
            ) : null}
            <span className="text-[10px] text-gray-400 ml-auto mr-2">{t('bots.builder.optional')}</span>
            <ChevronDown size={16} className={`text-gray-400 transition-transform duration-200 ${openNotif === 'discord' ? 'rotate-180' : ''}`} />
          </button>
          {openNotif === 'discord' && (
            <div className="px-3.5 pb-3.5 space-y-3">
              {discordConfigured && !discordWebhookUrl && (
                <div className="flex items-center gap-2 p-2 rounded-lg bg-emerald-500/10 border border-emerald-500/20">
                  <CheckCircle size={14} className="text-emerald-400 shrink-0" />
                  <span className="text-xs text-emerald-400">Discord ist konfiguriert. Leer lassen = bestehende Einstellung beibehalten.</span>
                </div>
              )}
              <div>
                <label htmlFor="notif-discord-webhook" className="block text-xs text-gray-300 mb-1.5">{t('bots.builder.discordWebhook')}</label>
                <input
                  id="notif-discord-webhook"
                  type="url"
                  value={discordWebhookUrl}
                  onChange={e => onDiscordWebhookUrlChange(e.target.value)}
                  placeholder="https://discord.com/api/webhooks/..."
                  className="filter-select w-full text-sm"
                />
                <p className="text-xs text-gray-400 mt-1.5">{t('bots.builder.discordWebhookHint')}</p>
              </div>
              {onTestDiscord && (discordConfigured || discordWebhookUrl) && (
                <button
                  type="button"
                  onClick={onTestDiscord}
                  className="px-3 py-1.5 text-xs bg-indigo-500/10 border border-indigo-500/20 text-indigo-400 rounded-lg hover:bg-indigo-500/20 transition-colors flex items-center gap-1.5"
                >
                  <svg viewBox="0 0 24 24" className="w-3.5 h-3.5" fill="currentColor"><path d="M20.317 4.37a19.791 19.791 0 0 0-4.885-1.515.074.074 0 0 0-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 0 0-5.487 0 12.64 12.64 0 0 0-.617-1.25.077.077 0 0 0-.079-.037A19.736 19.736 0 0 0 3.677 4.37a.07.07 0 0 0-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 0 0 .031.057 19.9 19.9 0 0 0 5.993 3.03.078.078 0 0 0 .084-.028c.462-.63.874-1.295 1.226-1.994a.076.076 0 0 0-.041-.106 13.107 13.107 0 0 1-1.872-.892.077.077 0 0 1-.008-.128 10.2 10.2 0 0 0 .372-.292.074.074 0 0 1 .077-.01c3.928 1.793 8.18 1.793 12.062 0a.074.074 0 0 1 .078.01c.12.098.246.198.373.292a.077.077 0 0 1-.006.127 12.299 12.299 0 0 1-1.873.892.077.077 0 0 0-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 0 0 .084.028 19.839 19.839 0 0 0 6.002-3.03.077.077 0 0 0 .032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 0 0-.031-.03zM8.02 15.33c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.956-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.956 2.418-2.157 2.418zm7.975 0c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.955-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.946 2.418-2.157 2.418z"/></svg>
                  Test senden
                </button>
              )}
              <div className="bg-indigo-900/15 border border-indigo-800/40 rounded-lg p-2.5 overflow-hidden">
                <p className="text-xs text-indigo-300 leading-relaxed break-words whitespace-pre-wrap">{t('bots.builder.discordSetupGuide')}</p>
              </div>
            </div>
          )}
        </div>

        {/* Telegram */}
        <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] overflow-hidden">
          <button
            type="button"
            onClick={() => onOpenNotifChange(openNotif === 'telegram' ? null : 'telegram')}
            className="w-full flex items-center gap-3 p-3.5 hover:bg-white/[0.02] transition-colors"
          >
            <svg viewBox="0 0 24 24" className="w-5 h-5 shrink-0" fill="#26A5E4"><path d="M11.944 0A12 12 0 0 0 0 12a12 12 0 0 0 12 12 12 12 0 0 0 12-12A12 12 0 0 0 12 0h-.056zm4.962 7.224c.1-.002.321.023.465.14a.506.506 0 0 1 .171.325c.016.093.036.306.02.472-.18 1.898-.962 6.502-1.36 8.627-.168.9-.499 1.201-.82 1.23-.696.065-1.225-.46-1.9-.902-1.056-.693-1.653-1.124-2.678-1.8-1.185-.78-.417-1.21.258-1.91.177-.184 3.247-2.977 3.307-3.23.007-.032.014-.15-.056-.212s-.174-.041-.249-.024c-.106.024-1.793 1.14-5.061 3.345-.479.33-.913.49-1.302.48-.428-.008-1.252-.241-1.865-.44-.752-.245-1.349-.374-1.297-.789.027-.216.325-.437.893-.663 3.498-1.524 5.83-2.529 6.998-3.014 3.332-1.386 4.025-1.627 4.476-1.635z"/></svg>
            <span className="text-sm font-medium text-white">Telegram</span>
            {(telegramBotToken || telegramConfigured) ? (
              <span className="flex items-center gap-1 text-[10px] text-emerald-400 font-medium"><Check size={12} /> aktiv</span>
            ) : null}
            <span className="text-[10px] text-gray-400 ml-auto mr-2">{t('bots.builder.optional')}</span>
            <ChevronDown size={16} className={`text-gray-400 transition-transform duration-200 ${openNotif === 'telegram' ? 'rotate-180' : ''}`} />
          </button>
          {openNotif === 'telegram' && (
            <div className="px-3.5 pb-3.5 space-y-3">
              {telegramConfigured && !telegramBotToken && (
                <div className="flex items-center gap-2 p-2 rounded-lg bg-emerald-500/10 border border-emerald-500/20">
                  <CheckCircle size={14} className="text-emerald-400 shrink-0" />
                  <span className="text-xs text-emerald-400">Telegram ist konfiguriert. Leer lassen = bestehende Einstellung beibehalten.</span>
                </div>
              )}
              <div>
                <label htmlFor="notif-telegram-token" className="block text-xs text-gray-300 mb-1.5">{t('bots.builder.telegramToken')}</label>
                <input
                  id="notif-telegram-token"
                  type="password"
                  value={telegramBotToken}
                  onChange={e => onTelegramBotTokenChange(e.target.value)}
                  placeholder="6123456789:ABCdef..."
                  className="filter-select w-full text-sm"
                />
              </div>
              <div>
                <label htmlFor="notif-telegram-chatid" className="block text-xs text-gray-300 mb-1.5">{t('bots.builder.telegramChatId')}</label>
                <input
                  id="notif-telegram-chatid"
                  type="text"
                  value={telegramChatId}
                  onChange={e => onTelegramChatIdChange(e.target.value)}
                  placeholder="123456789"
                  className="filter-select w-full text-sm"
                />
              </div>
              {onTestTelegram && (telegramConfigured || telegramBotToken) && (
                <button
                  type="button"
                  onClick={onTestTelegram}
                  className="px-3 py-1.5 text-xs bg-blue-500/10 border border-blue-500/20 text-blue-400 rounded-lg hover:bg-blue-500/20 transition-colors flex items-center gap-1.5"
                >
                  <svg viewBox="0 0 24 24" className="w-3.5 h-3.5" fill="currentColor"><path d="M11.944 0A12 12 0 0 0 0 12a12 12 0 0 0 12 12 12 12 0 0 0 12-12A12 12 0 0 0 12 0h-.056zm4.962 7.224c.1-.002.321.023.465.14a.506.506 0 0 1 .171.325c.016.093.036.306.02.472-.18 1.898-.962 6.502-1.36 8.627-.168.9-.499 1.201-.82 1.23-.696.065-1.225-.46-1.9-.902-1.056-.693-1.653-1.124-2.678-1.8-1.185-.78-.417-1.21.258-1.91.177-.184 3.247-2.977 3.307-3.23.007-.032.014-.15-.056-.212s-.174-.041-.249-.024c-.106.024-1.793 1.14-5.061 3.345-.479.33-.913.49-1.302.48-.428-.008-1.252-.241-1.865-.44-.752-.245-1.349-.374-1.297-.789.027-.216.325-.437.893-.663 3.498-1.524 5.83-2.529 6.998-3.014 3.332-1.386 4.025-1.627 4.476-1.635z"/></svg>
                  Test senden
                </button>
              )}
              <div className="bg-blue-500/5 dark:bg-blue-900/15 border border-blue-500/20 dark:border-blue-800/40 rounded-lg p-2.5 overflow-hidden">
                <p className="text-xs text-blue-600 dark:text-blue-300 leading-relaxed break-words [overflow-wrap:anywhere]">{t('bots.builder.telegramHint')}</p>
              </div>
            </div>
          )}
        </div>

        {/* PnL Alerts */}
        <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] overflow-hidden">
          <button
            type="button"
            onClick={() => onOpenNotifChange(openNotif === 'pnl' ? null : 'pnl')}
            className="w-full flex items-center gap-3 p-3.5 hover:bg-white/[0.02] transition-colors"
          >
            <Bell size={20} className="shrink-0 text-amber-400" />
            <span className="text-sm font-medium text-white">PnL-Alerts</span>
            {pnlAlertSettings.enabled && pnlAlertSettings.thresholds.length > 0 && (
              <span className="flex items-center gap-1 text-[10px] text-emerald-400 font-medium">
                <Check size={12} /> aktiv
              </span>
            )}
            <span className="text-[10px] text-gray-400 ml-auto mr-2">{t('bots.builder.optional')}</span>
            <ChevronDown size={16} className={`text-gray-400 transition-transform duration-200 ${openNotif === 'pnl' ? 'rotate-180' : ''}`} />
          </button>
          {openNotif === 'pnl' && (
            <div className="px-3.5 pb-3.5 space-y-4">
              {/* Toggle */}
              <label className="flex items-center justify-between cursor-pointer group">
                <span className="text-xs text-gray-300 group-hover:text-white transition-colors">
                  Benachrichtigen wenn PnL-Schwelle erreicht
                </span>
                <button
                  type="button"
                  role="switch"
                  aria-checked={pnlAlertSettings.enabled}
                  onClick={() => updateAlert({ enabled: !pnlAlertSettings.enabled })}
                  className={`relative w-10 h-5 rounded-full transition-colors ${
                    pnlAlertSettings.enabled ? 'bg-emerald-500' : 'bg-gray-600'
                  }`}
                >
                  <span
                    className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${
                      pnlAlertSettings.enabled ? 'translate-x-5' : ''
                    }`}
                  />
                </button>
              </label>

              {pnlAlertSettings.enabled && (
                <div className="space-y-4 animate-in fade-in duration-200">
                  {/* Mode selector: $ or % */}
                  <div>
                    <label className="block text-xs text-gray-400 mb-2">Schwellenwert-Typ</label>
                    <div className="flex gap-1 bg-gray-800/60 p-0.5 rounded-lg w-fit">
                      {([
                        { value: 'dollar' as const, label: '$ Betrag' },
                        { value: 'percent' as const, label: '% Prozent' },
                      ]).map((opt) => (
                        <button
                          key={opt.value}
                          type="button"
                          onClick={() => updateAlert({ mode: opt.value })}
                          className={`px-3 py-1.5 text-xs font-medium rounded-md transition-all ${
                            pnlAlertSettings.mode === opt.value
                              ? 'bg-amber-500/20 text-amber-300 ring-1 ring-amber-500/30'
                              : 'text-gray-500 hover:text-white hover:bg-white/5'
                          }`}
                        >
                          {opt.label}
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* Threshold chips + input */}
                  <ThresholdChipInput
                    thresholds={pnlAlertSettings.thresholds}
                    unit={pnlAlertSettings.mode === 'percent' ? '%' : '$'}
                    step={pnlAlertSettings.mode === 'percent' ? 0.5 : 1}
                    onChange={(thresholds) => updateAlert({ thresholds })}
                  />

                  {/* Direction selector */}
                  <div>
                    <label className="block text-xs text-gray-400 mb-2">Richtung</label>
                    <div className="flex gap-1 bg-gray-800/60 p-0.5 rounded-lg w-fit">
                      {([
                        { value: 'both' as const, label: 'Beides' },
                        { value: 'profit' as const, label: 'Gewinn' },
                        { value: 'loss' as const, label: 'Verlust' },
                      ]).map((opt) => (
                        <button
                          key={opt.value}
                          type="button"
                          onClick={() => updateAlert({ direction: opt.value })}
                          className={`px-3 py-1.5 text-xs font-medium rounded-md transition-all ${
                            pnlAlertSettings.direction === opt.value
                              ? 'bg-amber-500/20 text-amber-300 ring-1 ring-amber-500/30'
                              : 'text-gray-500 hover:text-white hover:bg-white/5'
                          }`}
                        >
                          {opt.label}
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* Info hint */}
                  <div className="bg-amber-900/10 border border-amber-800/30 rounded-lg p-2.5">
                    <p className="text-xs text-amber-300/80 leading-relaxed">
                      Du wirst <strong>einmalig pro Schwelle pro Trade</strong> benachrichtigt.
                      Bei mehreren Schwellenwerten erhältst du stufenweise Alerts (z.B. bei 5%, dann bei 10%).
                    </p>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        </div>
      </div>
    </div>
  )
}
