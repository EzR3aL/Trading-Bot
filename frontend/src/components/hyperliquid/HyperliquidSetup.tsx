/**
 * Inline Hyperliquid setup component for the Settings page.
 * Handles affiliate verification and builder fee approval
 * as a natural continuation of wallet credential setup.
 */
import { useState, useEffect, Component, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { WagmiProvider } from 'wagmi'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RainbowKitProvider, ConnectButton, darkTheme } from '@rainbow-me/rainbowkit'
import { useAccount, useWalletClient, useChainId } from 'wagmi'
import '@rainbow-me/rainbowkit/styles.css'
import { walletConfig } from '../../config/wallet'
import { CheckCircle, Loader2, ExternalLink, Wallet, AlertTriangle, Info } from 'lucide-react'
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

/**
 * Structured diagnostic returned by the backend's verify-referral endpoint.
 * Contains everything needed to render concrete "what to do next" instructions
 * instead of a generic error string. See #135.
 */
interface ReferralDiagnostic {
  error: string
  required_action: 'DEPOSIT_NEEDED' | 'ENTER_CODE_MANUALLY' | 'WRONG_REFERRER' | 'VERIFIED'
  wallet_address: string
  wallet_short: string
  account_value_usd: number
  cum_volume_usd: number
  referred_by: unknown
  referral_code: string
  referral_link: string
  min_deposit_usdc: number
  deposit_url: string
  enter_code_url: string
}

interface HyperliquidSetupProps {
  /** Called when all setup steps are complete */
  onComplete?: () => void
}

function HyperliquidSetupInner({ onComplete }: HyperliquidSetupProps) {
  const { t } = useTranslation()
  const { address, isConnected } = useAccount()
  const chainId = useChainId()
  const { data: walletClient } = useWalletClient()

  const [config, setConfig] = useState<BuilderConfig | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [referralDiag, setReferralDiag] = useState<ReferralDiagnostic | null>(null)

  // Step states
  const [referralVerified, setReferralVerified] = useState(false)
  const [builderFeeApproved, setBuilderFeeApproved] = useState(false)
  const [verifyingReferral, setVerifyingReferral] = useState(false)
  const [signingFee, setSigningFee] = useState(false)

  const fetchConfig = async () => {
    try {
      const res = await api.get('/config/hyperliquid/builder-config')
      const cfg = res.data as BuilderConfig
      setConfig(cfg)
      setReferralVerified(!cfg.referral_code || cfg.referral_verified)
      setBuilderFeeApproved(cfg.builder_fee_approved)
    } catch {
      setError(t('builderFee.loadError'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchConfig() }, [])

  // Notify parent when all steps are complete
  useEffect(() => {
    if (referralVerified && builderFeeApproved && onComplete) {
      onComplete()
    }
  }, [referralVerified, builderFeeApproved])

  const handleVerifyReferral = async () => {
    setError(null)
    setReferralDiag(null)
    setVerifyingReferral(true)
    try {
      await api.post('/config/hyperliquid/verify-referral')
      setReferralVerified(true)
    } catch (err: unknown) {
      const e = err as { response?: { data?: { detail?: ReferralDiagnostic | string } } }
      const detail = e.response?.data?.detail
      if (detail && typeof detail === 'object' && 'required_action' in detail) {
        // Structured diagnostic from backend — render a rich error block
        setReferralDiag(detail as ReferralDiagnostic)
        setError(null)
      } else {
        setError((typeof detail === 'string' ? detail : null) || t('builderFee.referralFailed'))
      }
    } finally {
      setVerifyingReferral(false)
    }
  }

  const handleSignBuilderFee = async () => {
    if (!config || !walletClient || !address) return
    setError(null)
    setSigningFee(true)

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

      // Wait for on-chain propagation
      await new Promise(resolve => setTimeout(resolve, 3000))

      await api.post('/config/hyperliquid/confirm-builder-approval', {
        wallet_address: address,
      })

      setBuilderFeeApproved(true)
    } catch (err: unknown) {
      const e = err as { code?: number; message?: string; response?: { data?: { detail?: string } } }
      if (e.code === 4001 || e.message?.includes('rejected')) {
        setError(t('builderFee.signRejected', 'Signing was rejected'))
      } else {
        setError(e.response?.data?.detail || e.message || t('builderFee.signFailed'))
      }
    } finally {
      setSigningFee(false)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center gap-2 py-4 text-gray-400 text-sm">
        <Loader2 className="w-4 h-4 animate-spin" />
        {t('common.loading')}
      </div>
    )
  }

  // Don't render if HL is not configured on the server
  if (!config?.builder_configured) return null

  const allDone = referralVerified && builderFeeApproved
  const hasReferralStep = !!config.referral_code

  // Count pending steps
  const pendingCount = (hasReferralStep && !referralVerified ? 1 : 0) + (!builderFeeApproved ? 1 : 0)

  return (
    <div className="mt-4 pt-4 border-t border-white/[0.06]">
      {/* Title */}
      <div className="flex items-center gap-2 mb-4">
        <Wallet className="w-4 h-4 text-emerald-400" />
        <h4 className="text-sm font-semibold text-white">{t('hlSetup.title')}</h4>
        {!allDone && pendingCount > 0 && (
          <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-400">
            {t('hlSetup.pendingSteps', { count: pendingCount })}
          </span>
        )}
      </div>

      {/* Progress checklist */}
      <div className="space-y-2 mb-4">
        {/* Step: Wallet connected (always true here) */}
        <div className="flex items-center gap-2 text-sm">
          <CheckCircle className="w-4 h-4 text-emerald-400 shrink-0" />
          <span className="text-emerald-400">{t('hlSetup.walletConnected')}</span>
        </div>

        {/* Step: Affiliate verified (only if referral configured) */}
        {hasReferralStep && (
          <div className="flex items-center gap-2 text-sm">
            {referralVerified ? (
              <>
                <CheckCircle className="w-4 h-4 text-emerald-400 shrink-0" />
                <span className="text-emerald-400">{t('hlSetup.affiliateVerified')}</span>
              </>
            ) : (
              <>
                <div className="w-4 h-4 rounded-full border-2 border-amber-400 shrink-0" />
                <span className="text-amber-400">{t('hlSetup.affiliateVerified')}</span>
              </>
            )}
          </div>
        )}

        {/* Step: Builder fee approved */}
        <div className="flex items-center gap-2 text-sm">
          {builderFeeApproved ? (
            <>
              <CheckCircle className="w-4 h-4 text-emerald-400 shrink-0" />
              <span className="text-emerald-400">{t('hlSetup.builderFeeApproved')}</span>
            </>
          ) : (
            <>
              <div className="w-4 h-4 rounded-full border-2 border-amber-400 shrink-0" />
              <span className="text-amber-400">{t('hlSetup.builderFeeApproved')}</span>
            </>
          )}
        </div>
      </div>

      {/* All done message */}
      {allDone && (
        <div className="space-y-2">
          <div className="p-3 bg-emerald-950/30 border border-emerald-700/20 rounded-lg text-sm text-emerald-400">
            {t('hlSetup.ready')}
          </div>
          {/* Builder wallet balance requirement hint */}
          <div className="flex items-start gap-2 p-3 bg-amber-500/10 border border-amber-500/20 rounded-lg text-xs text-amber-300">
            <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
            {t('hlSetup.builderWalletHint')}
          </div>
        </div>
      )}

      {/* Affiliate verification action */}
      {hasReferralStep && !referralVerified && (
        <div className="space-y-3 mb-4">
          <div className="p-3 bg-emerald-950/30 border border-emerald-700/20 rounded-lg">
            <p className="text-gray-300 text-xs mb-2">{t('hlSetup.affiliatePrompt')}</p>
            <a
              href={`https://app.hyperliquid.xyz/join/${config.referral_code}`}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 px-3 py-2 rounded-md bg-emerald-900/40 border border-emerald-700/30 text-emerald-400 hover:text-emerald-300 hover:bg-emerald-900/60 text-xs font-mono transition-colors"
            >
              app.hyperliquid.xyz/join/{config.referral_code}
              <ExternalLink className="w-3 h-3 shrink-0" />
            </a>
          </div>
          <button
            onClick={handleVerifyReferral}
            disabled={verifyingReferral}
            className="w-full py-2.5 bg-emerald-600 hover:bg-emerald-500 disabled:bg-gray-600 disabled:cursor-not-allowed text-white font-medium rounded-lg transition-colors flex items-center justify-center gap-2 text-sm"
          >
            {verifyingReferral ? (
              <><Loader2 className="w-4 h-4 animate-spin" /> {t('common.verifying', 'Verifiziere...')}</>
            ) : (
              t('hlSetup.affiliateCheck')
            )}
          </button>
        </div>
      )}

      {/* Builder fee signing action — only show after affiliate is verified */}
      {referralVerified && !builderFeeApproved && (
        <div className="space-y-3">
          <p className="text-gray-400 text-xs">{t('hlSetup.builderFeePrompt')}</p>
          {/* Builder wallet balance requirement hint */}
          <div className="flex items-start gap-2 p-2.5 bg-amber-500/10 border border-amber-500/20 rounded-lg text-xs text-amber-300">
            <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
            {t('hlSetup.builderWalletHint')}
          </div>

          {/* Wallet connect */}
          {!isConnected && (
            <div className="flex justify-center">
              <ConnectButton />
            </div>
          )}

          {/* Connected: show wallet info + sign button */}
          {isConnected && (
            <>
              <div className="flex items-center justify-between bg-white/[0.03] border border-white/10 rounded-lg p-3">
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
              <button
                onClick={handleSignBuilderFee}
                disabled={signingFee}
                className="w-full py-2.5 bg-emerald-600 hover:bg-emerald-500 disabled:bg-gray-600 disabled:cursor-not-allowed text-white font-medium rounded-lg transition-colors flex items-center justify-center gap-2 text-sm"
              >
                {signingFee ? (
                  <><Loader2 className="w-4 h-4 animate-spin" /> {t('builderFee.approving')}</>
                ) : (
                  t('builderFee.approve')
                )}
              </button>
            </>
          )}
        </div>
      )}

      {/* Error display — plain string fallback */}
      {error && (
        <div className="mt-3 bg-red-900/30 border border-red-700/50 rounded-lg p-3 text-sm text-red-300">
          {error}
        </div>
      )}

      {/* Structured referral diagnostic — rich error with next-step guidance */}
      {referralDiag && (
        <div className="mt-3 bg-red-900/20 border border-red-700/40 rounded-lg p-3 space-y-3">
          <div className="flex items-start gap-2">
            <AlertTriangle className="w-4 h-4 text-red-400 shrink-0 mt-0.5" />
            <p className="text-sm text-red-300 leading-relaxed">{referralDiag.error}</p>
          </div>

          {/* Wallet + HL account state */}
          <div className="grid grid-cols-2 gap-2 text-xs bg-black/30 rounded p-2">
            <div>
              <div className="text-gray-500">{t('hlSetup.diagWallet')}</div>
              <div className="text-white font-mono break-all">{referralDiag.wallet_short}</div>
            </div>
            <div>
              <div className="text-gray-500">{t('hlSetup.diagBalance')}</div>
              <div className={referralDiag.account_value_usd > 0 ? 'text-emerald-400' : 'text-amber-400'}>
                ${referralDiag.account_value_usd.toFixed(2)}
              </div>
            </div>
            <div>
              <div className="text-gray-500">{t('hlSetup.diagVolume')}</div>
              <div className="text-gray-300">${referralDiag.cum_volume_usd.toFixed(2)}</div>
            </div>
            <div>
              <div className="text-gray-500">{t('hlSetup.diagReferrer')}</div>
              <div className="text-gray-300">
                {referralDiag.referred_by
                  ? JSON.stringify(referralDiag.referred_by).slice(0, 24)
                  : t('hlSetup.diagNoReferrer')}
              </div>
            </div>
          </div>

          {/* Action-specific next steps */}
          {referralDiag.required_action === 'DEPOSIT_NEEDED' && (
            <div className="space-y-2 border-t border-red-700/30 pt-3">
              <div className="flex items-start gap-2 text-xs">
                <Info className="w-3.5 h-3.5 text-amber-400 shrink-0 mt-0.5" />
                <div className="text-gray-300">
                  <div className="font-semibold text-amber-400 mb-1">{t('hlSetup.depositStepTitle')}</div>
                  <ol className="list-decimal list-inside space-y-1 text-[11px] text-gray-400">
                    <li>{t('hlSetup.depositStep1', { min: referralDiag.min_deposit_usdc })}</li>
                    <li>{t('hlSetup.depositStep2')}</li>
                    <li>{t('hlSetup.depositStep3')}</li>
                  </ol>
                </div>
              </div>
              <a
                href={referralDiag.deposit_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 px-3 py-2 rounded-md bg-emerald-900/40 border border-emerald-700/30 text-emerald-400 hover:text-emerald-300 hover:bg-emerald-900/60 text-xs font-mono transition-colors"
              >
                {referralDiag.deposit_url.replace('https://', '')}
                <ExternalLink className="w-3 h-3 shrink-0" />
              </a>
            </div>
          )}

          {referralDiag.required_action === 'ENTER_CODE_MANUALLY' && (
            <div className="space-y-2 border-t border-red-700/30 pt-3">
              <div className="flex items-start gap-2 text-xs">
                <Info className="w-3.5 h-3.5 text-amber-400 shrink-0 mt-0.5" />
                <div className="text-gray-300">
                  <div className="font-semibold text-amber-400 mb-1">{t('hlSetup.enterCodeStepTitle')}</div>
                  <ol className="list-decimal list-inside space-y-1 text-[11px] text-gray-400">
                    <li>{t('hlSetup.enterCodeStep1')}</li>
                    <li>{t('hlSetup.enterCodeStep2', { code: referralDiag.referral_code })}</li>
                    <li>{t('hlSetup.enterCodeStep3')}</li>
                  </ol>
                </div>
              </div>
              <a
                href={referralDiag.enter_code_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 px-3 py-2 rounded-md bg-emerald-900/40 border border-emerald-700/30 text-emerald-400 hover:text-emerald-300 hover:bg-emerald-900/60 text-xs font-mono transition-colors"
              >
                {referralDiag.enter_code_url.replace('https://', '')}
                <ExternalLink className="w-3 h-3 shrink-0" />
              </a>
            </div>
          )}

          {referralDiag.required_action === 'WRONG_REFERRER' && (
            <div className="border-t border-red-700/30 pt-3 text-xs text-gray-400">
              {t('hlSetup.wrongReferrerHint')}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// Error boundary for wallet initialization failures
class WalletErrorBoundary extends Component<
  { children: ReactNode },
  { error: string | null }
> {
  state = { error: null as string | null }

  static getDerivedStateFromError(err: Error) {
    return { error: err.message }
  }

  render() {
    if (this.state.error) {
      return (
        <div className="mt-4 pt-4 border-t border-white/[0.06]">
          <div className="p-3 bg-red-900/20 border border-red-700/30 rounded-lg">
            <div className="flex items-center gap-2 mb-2">
              <AlertTriangle className="w-4 h-4 text-red-400" />
              <span className="text-sm font-medium text-red-400">Wallet Error</span>
            </div>
            <p className="text-xs text-gray-400">
              Set <code className="text-emerald-400">VITE_WALLETCONNECT_PROJECT_ID</code> in your <code>.env</code> file.
            </p>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}

/** Inline HL setup with wagmi/RainbowKit providers */
export default function HyperliquidSetup(props: HyperliquidSetupProps) {
  return (
    <WalletErrorBoundary>
      <WagmiProvider config={walletConfig}>
        <QueryClientProvider client={queryClient}>
          <RainbowKitProvider theme={darkTheme({
            accentColor: '#10b981',
            borderRadius: 'medium',
          })}>
            <HyperliquidSetupInner {...props} />
          </RainbowKitProvider>
        </QueryClientProvider>
      </WagmiProvider>
    </WalletErrorBoundary>
  )
}
