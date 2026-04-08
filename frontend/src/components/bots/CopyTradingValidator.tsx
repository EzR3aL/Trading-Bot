import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { CheckCircle2, AlertTriangle, XCircle, Loader2 } from 'lucide-react'
import { validateSourceWallet, type ValidateSourceResponse } from '../../api/copyTrading'

interface Props {
  wallet: string
  targetExchange: string
  onValidated: (result: ValidateSourceResponse | null) => void
}

export default function CopyTradingValidator({ wallet, targetExchange, onValidated }: Props) {
  const { t } = useTranslation()
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<ValidateSourceResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  const run = async () => {
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const r = await validateSourceWallet(wallet, targetExchange)
      setResult(r)
      onValidated(r)
    } catch (e: any) {
      const msg = e?.response?.data?.detail ?? (e instanceof Error ? e.message : String(e))
      setError(typeof msg === 'string' ? msg : JSON.stringify(msg))
      onValidated(null)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-2">
      <button
        type="button"
        onClick={run}
        disabled={!wallet || !targetExchange || loading}
        className="px-3 py-1.5 rounded-md text-xs bg-primary-500/15 text-primary-400 hover:bg-primary-500/25 disabled:opacity-40"
      >
        {loading ? <Loader2 size={14} className="animate-spin inline mr-1" /> : null}
        {t('bots.builder.copyTrading.validateButton', 'Wallet prüfen')}
      </button>

      {error && (
        <div className="flex items-start gap-2 p-2.5 rounded-md bg-red-500/10 border border-red-500/20 text-red-400 text-xs">
          <XCircle size={14} className="shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      {result && (
        <div className="p-2.5 rounded-md bg-emerald-500/10 border border-emerald-500/20 text-xs space-y-1">
          <div className="flex items-center gap-1.5 text-emerald-400 font-medium">
            <CheckCircle2 size={14} />
            {result.wallet_label} · {result.trades_30d}{' '}
            {t('bots.builder.copyTrading.tradesIn30d', 'Trades in 30 Tagen')}
          </div>
          <div className="text-emerald-300">
            {t('bots.builder.copyTrading.available', 'Verfügbar')}:{' '}
            {result.available.join(', ') || '—'}
          </div>
          {result.unavailable.length > 0 && (
            <div className="flex items-start gap-1.5 text-amber-400">
              <AlertTriangle size={12} className="shrink-0 mt-0.5" />
              <span>{result.warning}</span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
