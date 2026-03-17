import { useState, useEffect, Component, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { WagmiProvider } from 'wagmi'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RainbowKitProvider, ConnectButton, darkTheme } from '@rainbow-me/rainbowkit'
import { useAccount, useWalletClient, useChainId } from 'wagmi'
import '@rainbow-me/rainbowkit/styles.css'
import { walletConfig } from '../../config/wallet'
import { CheckCircle, AlertTriangle, Wallet, Loader2, ExternalLink, X, Link2 } from 'lucide-react'
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
  referral_required: boolean
  referral_verified: boolean
  needs_referral: boolean
}

interface BuilderFeeApprovalProps {
  onApproved: () => void
  onClose?: () => void
}

// Steps: 1=Referral, 2=Connect Wallet, 3=Sign Builder Fee, 4=Done
const TOTAL_STEPS = 4

function BuilderFeeApprovalInner({ onApproved, onClose }: BuilderFeeApprovalProps) {
  const { t } = useTranslation()
  const { address, isConnected } = useAccount()
  const chainId = useChainId()
  const { data: walletClient } = useWalletClient()

  const [config, setConfig] = useState<BuilderConfig | null>(null)
  const [loading, setLoading] = useState(true)
  const [step, setStep] = useState(1)
  const [processing, setProcessing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [confirmed, setConfirmed] = useState(false)
  const [referralVerified, setReferralVerified] = useState(false)
  const [verifyingReferral, setVerifyingReferral] = useState(false)

  useEffect(() => {
    const fetchConfig = async () => {
      try {
        const res = await api.get('/config/hyperliquid/builder-config')
        setConfig(res.data)
        const cfg = res.data as BuilderConfig

        // Determine starting step based on current state
        if (cfg.builder_fee_approved) {
          setConfirmed(true)
          setReferralVerified(true)
          setStep(TOTAL_STEPS)
        } else if (!cfg.referral_code || cfg.referral_verified) {
          // No referral required or already verified — skip to wallet
          setReferralVerified(true)
          setStep(2)
        }
        // else: step 1 (referral)
      } catch {
        setError(t('builderFee.loadError'))
      } finally {
        setLoading(false)
      }
    }
    fetchConfig()
  }, [])

  // Auto-advance from wallet step when connected
  useEffect(() => {
    if (isConnected && step === 2) {
      setStep(3)
    }
  }, [isConnected, step])

  const handleVerifyReferral = async () => {
    setError(null)
    setVerifyingReferral(true)
    try {
      await api.post('/config/hyperliquid/verify-referral')
      setReferralVerified(true)
      setStep(2)
    } catch (err: unknown) {
      const e = err as { response?: { data?: { detail?: string } } }
      setError(e.response?.data?.detail || t('builderFee.referralFailed', 'Referral-Verifizierung fehlgeschlagen. Hast du den Affiliate Link genutzt?'))
    } finally {
      setVerifyingReferral(false)
    }
  }

  const handleSignAndSubmit = async () => {
    if (!config || !walletClient || !address) return
    setError(null)
    setProcessing(true)

    try {
      const nonce = Date.now()
      const signatureChainIdHex = '0x' + chainId.toString(16)

      const signature = await walletClient.signTypedData({
        account: walletClient.account!,
        domain: {
          name: 'HyperliquidSignTransaction',
          version: '1',
          chainId,
          verifyingContract: '0x0000000000000000000000000000000000000000' as `0x${string}`,
        },
        types: {
          'HyperliquidTransaction:ApproveBuilderFee': [
            { name: 'hyperliquidChain', type: 'string' },
            { name: 'maxFeeRate', type: 'string' },
            { name: 'builder', type: 'address' },
            { name: 'nonce', type: 'uint64' },
          ],
        },
        primaryType: 'HyperliquidTransaction:ApproveBuilderFee' as const,
        message: {
          hyperliquidChain: 'Mainnet',
          maxFeeRate: config.max_fee_rate,
          builder: config.builder_address as `0x${string}`,
          nonce: BigInt(nonce),
        },
      })

      const r = signature.slice(0, 66)
      const s = '0x' + signature.slice(66, 130)
      const v = parseInt(signature.slice(130, 132), 16)

      const action = {
        type: 'approveBuilderFee',
        hyperliquidChain: 'Mainnet',
        maxFeeRate: config.max_fee_rate,
        builder: config.builder_address,
        nonce,
        signatureChainId: signatureChainIdHex,
      }

      const hlResponse = await fetch('https://api.hyperliquid.xyz/exchange', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          action,
          nonce,
          signature: { r, s, v },
          vaultAddress: null,
        }),
      })

      const hlBody = await hlResponse.json().catch(() => null)
      if (!hlResponse.ok) {
        throw new Error(`Hyperliquid: ${JSON.stringify(hlBody) || hlResponse.statusText}`)
      }
      if (hlBody?.status === 'err') {
        throw new Error(`Hyperliquid: ${hlBody.response || 'Unknown error'}`)
      }

      // Delay for on-chain propagation
      await new Promise(resolve => setTimeout(resolve, 3000))

      await api.post('/config/hyperliquid/confirm-builder-approval', {
        wallet_address: address,
      })

      setConfirmed(true)
      setStep(TOTAL_STEPS)
      setTimeout(() => onApproved(), 1500)
    } catch (err: unknown) {
      const e = err as { code?: number; message?: string; response?: { data?: { detail?: string } } }
      if (e.code === 4001 || e.message?.includes('rejected')) {
        setError(t('builderFee.signRejected', 'Signing was rejected'))
      } else {
        setError(e.response?.data?.detail || e.message || t('builderFee.signFailed'))
      }
    } finally {
      setProcessing(false)
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

  // Determine visible steps based on whether referral is required
  const hasReferralStep = !!config.referral_code
  const displaySteps = hasReferralStep ? TOTAL_STEPS : TOTAL_STEPS - 1
  const displayStep = hasReferralStep ? step : Math.max(1, step - 1)

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
        {Array.from({ length: displaySteps }, (_, i) => i + 1).map((s) => (
          <div key={s} className={`flex items-center ${s < displaySteps ? 'flex-1' : ''}`}>
            <div className={`w-7 h-7 rounded-full grid place-items-center text-[13px] font-semibold leading-none shrink-0 transition-colors ${
              displayStep >= s ? 'bg-emerald-500 text-white' : 'bg-gray-700 text-gray-400'
            }`}>
              {displayStep > s ? <CheckCircle className="w-3.5 h-3.5" /> : s}
            </div>
            {s < displaySteps && <div className={`flex-1 h-px mx-3 transition-colors ${displayStep > s ? 'bg-emerald-500' : 'bg-gray-600'}`} />}
          </div>
        ))}
      </div>

      {/* Step 1: Affiliate Link (only if referral required) */}
      {step === 1 && hasReferralStep && (
        <div className="space-y-4">
          <div className="bg-emerald-950/40 border border-emerald-700/30 rounded-lg px-4 py-4">
            <Link2 className="w-8 h-8 text-emerald-400 mx-auto mb-3" />
            <p className="text-emerald-300/90 text-sm leading-snug mb-3">
              {t('builderFee.referralRequired', 'Bevor du Hyperliquid nutzen kannst, registriere dich ueber unseren Affiliate Link:')}
            </p>
            <a
              href={`https://app.hyperliquid.xyz/join/${config.referral_code}`}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 px-3 py-2 rounded-md bg-emerald-900/40 border border-emerald-700/30 text-emerald-400 hover:text-emerald-300 hover:bg-emerald-900/60 text-xs font-mono transition-colors"
            >
              app.hyperliquid.xyz/join/{config.referral_code} <ExternalLink className="w-3 h-3 shrink-0" />
            </a>
          </div>

          <p className="text-gray-400 text-xs">
            {t('builderFee.referralHint', 'Nachdem du dich registriert hast, klicke auf "Verifizieren".')}
          </p>

          <button
            onClick={handleVerifyReferral}
            disabled={verifyingReferral}
            className="w-full py-3 bg-emerald-600 hover:bg-emerald-500 disabled:bg-gray-600 disabled:cursor-not-allowed text-white font-medium rounded-lg transition-colors flex items-center justify-center gap-2"
          >
            {verifyingReferral ? (
              <><Loader2 className="w-4 h-4 animate-spin" /> {t('common.verifying', 'Verifiziere...')}</>
            ) : (
              <><CheckCircle className="w-4 h-4" /> {t('builderFee.verifyReferral', 'Verifizieren')}</>
            )}
          </button>

          {error && (
            <div className="bg-red-900/30 border border-red-700/50 rounded-lg p-3 text-sm text-red-300 text-left">
              {error}
            </div>
          )}
        </div>
      )}

      {/* Step 2: Connect Wallet */}
      {step === 2 && (
        <div className="space-y-5">
          {referralVerified && hasReferralStep && (
            <div className="flex items-center gap-2 bg-emerald-950/30 border border-emerald-700/20 rounded-lg px-3 py-2 text-xs text-emerald-400">
              <CheckCircle className="w-4 h-4 shrink-0" />
              {t('builderFee.referralConfirmed', 'Affiliate Link verifiziert')}
            </div>
          )}
          <p className="text-gray-300 text-sm leading-relaxed">{t('builderFee.description')}</p>
          <div className="flex justify-center">
            <ConnectButton />
          </div>
        </div>
      )}

      {/* Step 3: Sign Builder Fee */}
      {step === 3 && (
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

          <button
            onClick={handleSignAndSubmit}
            disabled={processing}
            className="w-full py-3 bg-emerald-600 hover:bg-emerald-500 disabled:bg-gray-600 disabled:cursor-not-allowed text-white font-medium rounded-lg transition-colors flex items-center justify-center gap-2"
          >
            {processing ? (
              <><Loader2 className="w-4 h-4 animate-spin" /> {t('builderFee.approving')}</>
            ) : (
              t('builderFee.approve')
            )}
          </button>

          {error && (
            <div className="bg-red-900/30 border border-red-700/50 rounded-lg p-3 text-sm text-red-300 text-left">
              {error}
            </div>
          )}
        </div>
      )}

      {/* Step 4: Confirmed */}
      {step === TOTAL_STEPS && confirmed && (
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
