import { useState, useEffect, Component, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { WagmiProvider } from 'wagmi'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RainbowKitProvider, ConnectButton, darkTheme } from '@rainbow-me/rainbowkit'
import { useAccount, useSignTypedData } from 'wagmi'
import { keccak256, toBytes } from 'viem'
import '@rainbow-me/rainbowkit/styles.css'
import { walletConfig } from '../../config/wallet'
import { CheckCircle, AlertTriangle, Wallet, Loader2, ExternalLink, X } from 'lucide-react'
import api from '../../api/client'

const queryClient = new QueryClient()

interface BuilderConfig {
  builder_configured: boolean
  builder_address: string
  builder_fee: number
  max_fee_rate: string
  chain_id: number
  has_hl_connection: boolean
  builder_fee_approved: boolean
  needs_approval: boolean
  referral_code: string
}

interface BuilderFeeApprovalProps {
  onApproved: () => void
  onClose?: () => void
}

function BuilderFeeApprovalInner({ onApproved, onClose }: BuilderFeeApprovalProps) {
  const { t } = useTranslation()
  const { address, isConnected } = useAccount()
  const { signTypedData, isPending: isSigning, isSuccess: signSuccess, data: signature, error: signError, reset: resetSign } = useSignTypedData()

  const [config, setConfig] = useState<BuilderConfig | null>(null)
  const [loading, setLoading] = useState(true)
  const [step, setStep] = useState(1)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [confirmed, setConfirmed] = useState(false)
  const [nonce, setNonce] = useState(0)

  // Load builder config from backend
  useEffect(() => {
    const fetchConfig = async () => {
      try {
        const res = await api.get('/config/hyperliquid/builder-config')
        setConfig(res.data)
        if (res.data.builder_fee_approved) {
          setConfirmed(true)
          setStep(3)
        }
      } catch {
        setError(t('builderFee.loadError'))
      } finally {
        setLoading(false)
      }
    }
    fetchConfig()
  }, [])

  // When wallet connects, advance to step 2
  useEffect(() => {
    if (isConnected && step === 1) {
      setStep(2)
    }
  }, [isConnected, step])

  // After signing succeeds, submit to HL API then confirm with backend
  useEffect(() => {
    if (signSuccess && signature && !submitting && !confirmed) {
      submitApproval(signature)
    }
  }, [signSuccess, signature])

  const handleSign = () => {
    if (!config) return
    setError(null)
    resetSign()

    const ts = Date.now()
    setNonce(ts)

    const action = {
      type: 'approveBuilderFee' as const,
      hyperliquidChain: 'Mainnet' as const,
      maxFeeRate: config.max_fee_rate,
      builder: config.builder_address,
      nonce: ts,
    }

    // Hyperliquid Phantom Agent: compact JSON with sorted keys, then hash
    const sortedKeys = Object.keys(action).sort() as (keyof typeof action)[]
    const sorted: Record<string, unknown> = {}
    for (const k of sortedKeys) sorted[k] = action[k]
    const actionHash = keccak256(toBytes(JSON.stringify(sorted)))

    signTypedData({
      domain: {
        name: 'Exchange',
        version: '1',
        chainId: config.chain_id,
        verifyingContract: '0x0000000000000000000000000000000000000000' as `0x${string}`,
      },
      types: {
        Agent: [
          { name: 'source', type: 'string' },
          { name: 'connectionId', type: 'bytes32' },
        ],
      },
      primaryType: 'Agent',
      message: {
        source: 'a',
        connectionId: actionHash,
      },
    })
  }

  const submitApproval = async (sig: string) => {
    if (!config) return
    setSubmitting(true)
    setError(null)

    try {
      // Build the action object (same as signed)
      const action = {
        type: 'approveBuilderFee',
        hyperliquidChain: 'Mainnet',
        maxFeeRate: config.max_fee_rate,
        builder: config.builder_address,
        nonce: nonce,
      }

      // Parse signature into r, s, v
      const r = sig.slice(0, 66)
      const s = '0x' + sig.slice(66, 130)
      const v = parseInt(sig.slice(130, 132), 16)

      // Send directly to Hyperliquid Exchange API
      const hlResponse = await fetch('https://api.hyperliquid.xyz/exchange', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          action,
          nonce: nonce,
          signature: { r, s, v },
        }),
      })

      if (!hlResponse.ok) {
        const body = await hlResponse.text()
        throw new Error(`Hyperliquid: ${body}`)
      }

      // Confirm with our backend (verifies on-chain + saves DB flag)
      await api.post('/config/hyperliquid/confirm-builder-approval')

      setConfirmed(true)
      setStep(3)

      // Wait a moment, then call onApproved
      setTimeout(() => onApproved(), 1500)
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || t('builderFee.signFailed'))
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) {
    return (
      <div className="bg-white/[0.03] rounded-xl border border-white/10 p-6 max-w-md w-full mx-auto text-center">
        <div className="flex items-center justify-center gap-3 py-8">
          <Loader2 className="w-6 h-6 animate-spin text-emerald-400" />
          <span className="text-gray-300">{t('common.loading')}</span>
        </div>
      </div>
    )
  }

  if (error && !config) {
    return (
      <div className="bg-white/[0.03] rounded-xl border border-red-700/50 p-6 max-w-md w-full mx-auto text-center">
        <AlertTriangle className="w-10 h-10 text-red-400 mx-auto mb-3" />
        <h3 className="text-lg font-semibold text-red-400 mb-2">{t('common.errorShort')}</h3>
        <p className="text-gray-300 text-sm mb-4">{error}</p>
        {onClose && (
          <button onClick={onClose} className="px-4 py-2 bg-gray-700 hover:bg-gray-600 text-white rounded-lg text-sm transition-colors">
            {t('common.cancel')}
          </button>
        )}
      </div>
    )
  }

  if (!config?.builder_configured) {
    return (
      <div className="bg-white/[0.03] rounded-xl border border-white/10 p-6 max-w-md w-full mx-auto text-center">
        <Wallet className="w-10 h-10 text-emerald-400 mx-auto mb-3" />
        <h3 className="text-lg font-semibold text-white mb-2">{t('builderFee.title')}</h3>
        <p className="text-gray-300 text-sm mb-4">{t('builderFee.notConfigured')}</p>
        {onClose && (
          <button onClick={onClose} className="px-4 py-2 bg-gray-700 hover:bg-gray-600 text-white rounded-lg text-sm transition-colors">
            {t('common.cancel')}
          </button>
        )}
      </div>
    )
  }

  return (
    <div className="bg-white/[0.03] rounded-xl border border-white/10 p-6 max-w-md w-full mx-auto text-center">
      {/* Header */}
      <div className="relative mb-5">
        <div className="flex items-center justify-center gap-2.5">
          <Wallet className="w-5 h-5 text-emerald-400" />
          <h3 className="text-lg font-semibold text-white">{t('builderFee.title')}</h3>
        </div>
        {onClose && (
          <button onClick={onClose} className="absolute top-0 right-0 text-gray-400 hover:text-white transition-colors">
            <X className="w-5 h-5" />
          </button>
        )}
      </div>

      {/* Progress steps */}
      <div className="flex items-center mb-6 px-6">
        {[1, 2, 3].map((s) => (
          <div key={s} className={`flex items-center ${s < 3 ? 'flex-1' : ''}`}>
            <div className={`w-7 h-7 rounded-full grid place-items-center text-[13px] font-semibold leading-none shrink-0 transition-colors ${
              step >= s ? 'bg-emerald-500 text-white' : 'bg-gray-700 text-gray-400'
            }`}>
              {step > s ? <CheckCircle className="w-3.5 h-3.5" /> : s}
            </div>
            {s < 3 && <div className={`flex-1 h-px mx-3 transition-colors ${step > s ? 'bg-emerald-500' : 'bg-gray-600'}`} />}
          </div>
        ))}
      </div>

      {/* Affiliate link */}
      {config.referral_code && step < 3 && (
        <div className="bg-emerald-950/40 border border-emerald-700/30 rounded-lg px-4 py-3 mb-5">
          <p className="text-emerald-300/90 text-[13px] leading-snug mb-2">{t('builderFee.affiliateHint')}</p>
          <a
            href={`https://app.hyperliquid.xyz/join/${config.referral_code}`}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-emerald-900/40 border border-emerald-700/30 text-emerald-400 hover:text-emerald-300 hover:bg-emerald-900/60 text-xs font-mono transition-colors"
          >
            app.hyperliquid.xyz/join/{config.referral_code} <ExternalLink className="w-3 h-3 shrink-0" />
          </a>
        </div>
      )}

      {/* Step 1: Connect Wallet */}
      {step === 1 && (
        <div className="space-y-5">
          <p className="text-gray-300 text-sm leading-relaxed">{t('builderFee.description')}</p>
          <div className="flex justify-center">
            <ConnectButton />
          </div>
        </div>
      )}

      {/* Step 2: Sign */}
      {step === 2 && (
        <div className="space-y-4">
          {/* Connected wallet info */}
          <div className="flex items-center justify-between bg-white/[0.03] border border-white/10 rounded-xl p-3">
            <div className="text-left">
              <p className="text-xs text-gray-400">{t('builderFee.walletConnected')}</p>
              <p className="text-sm text-white font-mono">
                {address?.slice(0, 8)}...{address?.slice(-6)}
              </p>
            </div>
            <ConnectButton.Custom>
              {({ openAccountModal }) => (
                <button onClick={openAccountModal} className="text-xs text-emerald-400 hover:text-emerald-300">
                  {t('common.change')}
                </button>
              )}
            </ConnectButton.Custom>
          </div>

          <p className="text-gray-400 text-sm leading-relaxed">{t('builderFee.signHint')}</p>

          {/* Sign button */}
          <button
            onClick={handleSign}
            disabled={isSigning || submitting}
            className="w-full py-3 bg-emerald-600 hover:bg-emerald-500 disabled:bg-gray-600 disabled:cursor-not-allowed text-white font-medium rounded-lg transition-colors flex items-center justify-center gap-2"
          >
            {isSigning || submitting ? (
              <><Loader2 className="w-4 h-4 animate-spin" /> {t('builderFee.approving')}</>
            ) : (
              t('builderFee.approve')
            )}
          </button>

          {/* Error */}
          {(error || signError) && (
            <div className="bg-red-900/30 border border-red-700/50 rounded-lg p-3 text-sm text-red-300 text-left">
              {error || signError?.message || t('builderFee.signFailed')}
            </div>
          )}
        </div>
      )}

      {/* Step 3: Confirmed */}
      {step === 3 && confirmed && (
        <div className="space-y-3 py-2">
          <CheckCircle className="w-12 h-12 text-green-400 mx-auto" />
          <p className="text-green-400 font-semibold">{t('builderFee.approved')}</p>
          <p className="text-gray-400 text-sm">{t('builderFee.approvedHint')}</p>
        </div>
      )}
    </div>
  )
}

// Error boundary to catch RainbowKit/wagmi initialization crashes
class WalletErrorBoundary extends Component<
  { children: ReactNode; onClose?: () => void },
  { error: string | null }
> {
  state = { error: null as string | null }

  static getDerivedStateFromError(err: Error) {
    return { error: err.message }
  }

  render() {
    if (this.state.error) {
      return (
        <div className="bg-white/[0.03] rounded-xl border border-red-700/50 p-6 max-w-md w-full mx-auto text-center">
          <AlertTriangle className="w-10 h-10 text-red-400 mx-auto mb-3" />
          <h3 className="text-lg font-semibold text-red-400 mb-2">Wallet Error</h3>
          <p className="text-gray-300 text-sm mb-3">
            Failed to initialize wallet connection. This may be caused by a missing WalletConnect Project ID.
          </p>
          <pre className="text-xs text-red-300 bg-gray-900 rounded p-2 mb-4 overflow-auto text-left">
            {this.state.error}
          </pre>
          <p className="text-gray-400 text-xs mb-4">
            Set <code className="text-emerald-400">VITE_WALLETCONNECT_PROJECT_ID</code> in your <code>.env</code> file.
            Get a free ID at <a href="https://cloud.reown.com" target="_blank" rel="noopener noreferrer" className="text-emerald-400 underline">cloud.reown.com</a>
          </p>
          {this.props.onClose && (
            <button onClick={this.props.onClose} className="px-4 py-2 bg-gray-700 hover:bg-gray-600 text-white rounded-lg text-sm transition-colors">
              Close
            </button>
          )}
        </div>
      )
    }
    return this.props.children
  }
}

// Wrapper that provides wagmi + RainbowKit context
export default function BuilderFeeApproval(props: BuilderFeeApprovalProps) {
  return (
    <WalletErrorBoundary onClose={props.onClose}>
      <WagmiProvider config={walletConfig}>
        <QueryClientProvider client={queryClient}>
          <RainbowKitProvider theme={darkTheme({
            accentColor: '#10b981',
            borderRadius: 'medium',
          })}>
            <BuilderFeeApprovalInner {...props} />
          </RainbowKitProvider>
        </QueryClientProvider>
      </WagmiProvider>
    </WalletErrorBoundary>
  )
}
