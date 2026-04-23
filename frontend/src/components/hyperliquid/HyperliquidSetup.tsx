/**
 * Inline Hyperliquid setup component for the Settings page.
 * Handles affiliate verification and builder fee approval
 * as a natural continuation of wallet credential setup.
 */
import { useState, useEffect, useCallback, useRef, Component, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { WagmiProvider } from 'wagmi'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RainbowKitProvider, ConnectButton, darkTheme } from '@rainbow-me/rainbowkit'
import { useAccount, useWalletClient, useChainId } from 'wagmi'
import '@rainbow-me/rainbowkit/styles.css'
import { walletConfig } from '../../config/wallet'
import { CheckCircle, Loader2, ExternalLink, Wallet, AlertTriangle, Info } from 'lucide-react'
import api from '../../api/client'
import CopyButton from '../ui/CopyButton'

const queryClient = new QueryClient()

// On-chain confirmation polling config.
// Hyperliquid's L1 state can lag 1-5s after a successful signed action,
// occasionally longer under RPC load. Poll until the backend confirms the
// approved fee landed, or give up after MAX_POLL_MS to show a clear error.
const POLL_INTERVAL_MS = 1000
const MAX_POLL_MS = 30_000

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
  // Elapsed seconds while polling the backend for on-chain approval.
  // null = not polling, number = seconds elapsed (shown next to the spinner).
  const [pollElapsedSec, setPollElapsedSec] = useState<number | null>(null)
  // Abort flag so unmount/cleanup can stop an in-flight poll loop.
  const pollAbortRef = useRef(false)

  const fetchConfig = useCallback(async () => {
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
  }, [t])

  useEffect(() => { fetchConfig() }, [fetchConfig])

  // Stop any in-flight poll loop on unmount.
  useEffect(() => {
    return () => {
      pollAbortRef.current = true
    }
  }, [])

  // Notify parent when all steps are complete
  useEffect(() => {
    if (referralVerified && builderFeeApproved && onComplete) {
      onComplete()
    }
  }, [referralVerified, builderFeeApproved, onComplete])

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

      // Poll the backend for on-chain confirmation instead of a fixed sleep.
      // The /confirm-builder-approval endpoint returns 200 once HL reports the
      // approved fee, otherwise 400. We retry every POLL_INTERVAL_MS up to
      // MAX_POLL_MS, pausing while the tab is hidden so we don't burn requests
      // for a user who walked away.
      pollAbortRef.current = false
      setPollElapsedSec(0)
      const startedAt = Date.now()
      let confirmed = false
      let lastPollError: unknown = null

      while (!pollAbortRef.current && Date.now() - startedAt < MAX_POLL_MS) {
        await new Promise(resolve => setTimeout(resolve, POLL_INTERVAL_MS))

        if (pollAbortRef.current) break

        // Skip the request entirely while the tab is backgrounded. The elapsed
        // counter keeps advancing so the user sees real time, but we don't
        // spam the server. As soon as they return, the next tick will fire.
        if (typeof document !== 'undefined' && document.visibilityState !== 'visible') {
          setPollElapsedSec(Math.floor((Date.now() - startedAt) / 1000))
          continue
        }

        setPollElapsedSec(Math.floor((Date.now() - startedAt) / 1000))

        try {
          await api.post('/config/hyperliquid/confirm-builder-approval', {
            wallet_address: address,
          })
          confirmed = true
          break
        } catch (pollErr: unknown) {
          // 400 = approval not on-chain yet, keep polling.
          // Record in case we time out so we can surface the backend message.
          lastPollError = pollErr
        }
      }

      setPollElapsedSec(null)

      if (!confirmed) {
        const e = lastPollError as
          | { response?: { data?: { detail?: string } } }
          | undefined
        const backendDetail = e?.response?.data?.detail
        throw new Error(
          backendDetail ||
            t('hyperliquid.setup.pollTimeout', 'Approval did not land on-chain within 30s. Try again.')
        )
      }

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
      setPollElapsedSec(null)
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

  // Build the step list once — indexing respects whether referral step exists
  type StepState = 'done' | 'active' | 'pending'
  const steps: { num: number; label: string; state: StepState }[] = [
    { num: 1, label: t('hlSetup.walletConnected'), state: 'done' },
  ]
  if (hasReferralStep) {
    steps.push({
      num: 2,
      label: t('hlSetup.affiliateVerified'),
      state: referralVerified ? 'done' : 'active',
    })
  }
  steps.push({
    num: hasReferralStep ? 3 : 2,
    label: t('hlSetup.builderFeeApproved'),
    state: builderFeeApproved
      ? 'done'
      : hasReferralStep && !referralVerified
        ? 'pending'
        : 'active',
  })

  return (
    <div className="mt-4 pt-4 border-t border-white/[0.06]">
      {/* ═══ Header ═══ */}
      <div className="flex items-start gap-3 mb-5">
        <div className="w-11 h-11 rounded-xl bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center shrink-0">
          <Wallet className="w-5 h-5 text-emerald-400" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h4 className="text-base font-semibold text-white">{t('hlSetup.title')}</h4>
            {allDone ? (
              <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-emerald-500/15 border border-emerald-500/30 text-emerald-400 uppercase tracking-wide">
                {t('hlSetup.ready').split('!')[0] || 'Bereit'}
              </span>
            ) : pendingCount > 0 ? (
              <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-amber-500/15 border border-amber-500/30 text-amber-400">
                {t('hlSetup.pendingSteps', { count: pendingCount })}
              </span>
            ) : null}
          </div>
          <p className="text-xs text-gray-500 mt-0.5 leading-relaxed">
            {allDone
              ? t('hlSetup.ready')
              : t('hlSetup.subtitle', 'Schließe alle Schritte ab um mit Hyperliquid zu handeln')}
          </p>
        </div>
      </div>

      {/* ═══ Progress steps (numbered cards) ═══ */}
      <div className="space-y-2 mb-5">
        {steps.map((step) => (
          <div
            key={step.num}
            className={`flex items-center gap-3 px-3 py-2.5 rounded-lg border transition-all ${
              step.state === 'done'
                ? 'bg-emerald-500/[0.06] border-emerald-500/20'
                : step.state === 'active'
                  ? 'bg-amber-500/[0.08] border-amber-500/30'
                  : 'bg-white/[0.02] border-white/5'
            }`}
          >
            <div
              className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 font-bold text-xs ${
                step.state === 'done'
                  ? 'bg-emerald-500 text-white'
                  : step.state === 'active'
                    ? 'bg-amber-500 text-white'
                    : 'bg-white/5 text-gray-500'
              }`}
            >
              {step.state === 'done' ? (
                <CheckCircle className="w-4 h-4" />
              ) : (
                String(step.num).padStart(2, '0')
              )}
            </div>
            <span
              className={`text-sm font-medium ${
                step.state === 'done'
                  ? 'text-emerald-300'
                  : step.state === 'active'
                    ? 'text-amber-100'
                    : 'text-gray-500'
              }`}
            >
              {step.label}
            </span>
          </div>
        ))}
      </div>

      {/* ═══ All done — builder wallet hint ═══ */}
      {allDone && (
        <div className="flex items-start gap-2.5 p-3.5 bg-amber-500/10 border border-amber-500/20 rounded-xl text-xs text-amber-200 leading-relaxed">
          <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5 text-amber-400" />
          <span>{t('hlSetup.builderWalletHint')}</span>
        </div>
      )}

      {/* ═══ Affiliate verification action card ═══ */}
      {hasReferralStep && !referralVerified && (
        <div className="border border-amber-500/30 bg-amber-500/[0.05] rounded-xl p-4 space-y-3">
          <p className="text-sm text-gray-200 leading-relaxed">
            {t('hlSetup.affiliatePrompt')}
          </p>
          <a
            href={`https://app.hyperliquid.xyz/join/${config.referral_code}`}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center justify-between gap-2 px-3.5 py-2.5 rounded-lg bg-white/[0.04] border border-white/10 hover:border-emerald-500/40 hover:bg-emerald-500/[0.04] transition-all group"
          >
            <span className="text-xs font-mono text-gray-300 group-hover:text-emerald-300 truncate">
              app.hyperliquid.xyz/join/{config.referral_code}
            </span>
            <ExternalLink className="w-3.5 h-3.5 shrink-0 text-gray-500 group-hover:text-emerald-400" />
          </a>
          <button
            onClick={handleVerifyReferral}
            disabled={verifyingReferral}
            className="w-full py-3 bg-emerald-500 hover:bg-emerald-400 disabled:bg-gray-700 disabled:cursor-not-allowed text-white font-semibold rounded-lg shadow-lg shadow-emerald-500/20 transition-all flex items-center justify-center gap-2 text-sm"
          >
            {verifyingReferral ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                {t('common.verifying', 'Verifiziere...')}
              </>
            ) : (
              t('hlSetup.affiliateCheck')
            )}
          </button>
        </div>
      )}

      {/* ═══ Builder fee signing action card ═══ */}
      {referralVerified && !builderFeeApproved && (
        <div className="border border-amber-500/30 bg-amber-500/[0.05] rounded-xl p-4 space-y-3">
          <p className="text-sm text-gray-200 leading-relaxed">
            {t('hlSetup.builderFeePrompt')}
          </p>

          <div className="flex items-start gap-2.5 p-3 bg-black/20 border border-white/[0.06] rounded-lg text-xs text-amber-200 leading-relaxed">
            <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5 text-amber-400" />
            <span>{t('hlSetup.builderWalletHint')}</span>
          </div>

          {!isConnected && (
            <div className="flex justify-center py-1">
              <ConnectButton />
            </div>
          )}

          {isConnected && (
            <>
              <div className="flex items-center justify-between gap-3 bg-white/[0.04] border border-white/10 rounded-lg px-3.5 py-2.5">
                <div className="min-w-0 flex-1">
                  <p className="text-[10px] uppercase tracking-wide text-gray-500 mb-0.5">
                    {t('builderFee.walletConnected')}
                  </p>
                  <p className="text-xs text-white font-mono truncate">
                    {address?.slice(0, 8)}...{address?.slice(-6)}
                  </p>
                </div>
                <ConnectButton.Custom>
                  {({ openAccountModal }) => (
                    <button
                      onClick={openAccountModal}
                      className="text-xs text-emerald-400 hover:text-emerald-300 font-medium shrink-0"
                    >
                      {t('common.change')}
                    </button>
                  )}
                </ConnectButton.Custom>
              </div>
              <button
                onClick={handleSignBuilderFee}
                disabled={signingFee}
                className="w-full py-3 bg-emerald-500 hover:bg-emerald-400 disabled:bg-gray-700 disabled:cursor-not-allowed text-white font-semibold rounded-lg shadow-lg shadow-emerald-500/20 transition-all flex items-center justify-center gap-2 text-sm"
              >
                {signingFee ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    {pollElapsedSec !== null
                      ? t('hyperliquid.setup.pollingStatus', {
                          seconds: pollElapsedSec,
                          defaultValue: 'Checking on-chain status… ({{seconds}}s)',
                        })
                      : t('builderFee.approving')}
                  </>
                ) : (
                  t('builderFee.approve')
                )}
              </button>
            </>
          )}
        </div>
      )}

      {/* ═══ Plain string error fallback ═══ */}
      {error && (
        <div className="mt-3 flex items-start gap-2.5 p-3.5 bg-red-500/10 border border-red-500/30 rounded-xl text-sm text-red-200 leading-relaxed">
          <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5 text-red-400" />
          <span>{error}</span>
        </div>
      )}

      {/* ═══ Structured referral diagnostic — rich block ═══ */}
      {referralDiag && (
        <div className="mt-3 border border-red-500/30 bg-red-500/[0.05] rounded-xl overflow-hidden">
          {/* Error banner */}
          <div className="flex items-start gap-2.5 p-4 border-b border-red-500/20 bg-red-500/[0.04]">
            <div className="w-8 h-8 rounded-lg bg-red-500/15 border border-red-500/30 flex items-center justify-center shrink-0">
              <AlertTriangle className="w-4 h-4 text-red-400" />
            </div>
            <p className="text-sm text-red-100 leading-relaxed flex-1 pt-1">
              {referralDiag.error}
            </p>
          </div>

          {/* Wallet state summary — 2 columns */}
          <div className="grid grid-cols-2 gap-px bg-white/[0.03]">
            <div className="p-3 bg-black/20">
              <div className="text-[10px] uppercase tracking-wide text-gray-500 mb-1">
                {t('hlSetup.diagWallet')}
              </div>
              <div className="text-sm text-white font-mono flex items-center gap-1.5">
                <span>{referralDiag.wallet_short}</span>
                <CopyButton value={referralDiag.wallet_address} label={t('hlSetup.diagWallet')} />
              </div>
            </div>
            <div className="p-3 bg-black/20">
              <div className="text-[10px] uppercase tracking-wide text-gray-500 mb-1">
                {t('hlSetup.diagBalance')}
              </div>
              <div
                className={`text-sm font-semibold ${
                  referralDiag.account_value_usd > 0 ? 'text-emerald-400' : 'text-amber-400'
                }`}
              >
                ${referralDiag.account_value_usd.toFixed(2)}
              </div>
            </div>
            <div className="p-3 bg-black/20">
              <div className="text-[10px] uppercase tracking-wide text-gray-500 mb-1">
                {t('hlSetup.diagVolume')}
              </div>
              <div className="text-sm text-gray-200">
                ${referralDiag.cum_volume_usd.toFixed(2)}
              </div>
            </div>
            <div className="p-3 bg-black/20">
              <div className="text-[10px] uppercase tracking-wide text-gray-500 mb-1">
                {t('hlSetup.diagReferrer')}
              </div>
              <div className="text-sm text-gray-300 truncate">
                {referralDiag.referred_by
                  ? JSON.stringify(referralDiag.referred_by).slice(0, 24)
                  : t('hlSetup.diagNoReferrer')}
              </div>
            </div>
          </div>

          {/* Action-specific next steps */}
          {referralDiag.required_action === 'DEPOSIT_NEEDED' && (
            <div className="p-4 space-y-3">
              <div className="flex items-start gap-2.5">
                <div className="w-7 h-7 rounded-lg bg-amber-500/15 border border-amber-500/30 flex items-center justify-center shrink-0">
                  <Info className="w-3.5 h-3.5 text-amber-400" />
                </div>
                <div className="flex-1 min-w-0 pt-0.5">
                  <div className="text-sm font-semibold text-amber-300 mb-2">
                    {t('hlSetup.depositStepTitle')}
                  </div>
                  <ol className="space-y-1.5 text-xs text-gray-300 leading-relaxed">
                    <li className="flex gap-2">
                      <span className="text-gray-500 shrink-0">1.</span>
                      <span>{t('hlSetup.depositStep1', { min: referralDiag.min_deposit_usdc })}</span>
                    </li>
                    <li className="flex gap-2">
                      <span className="text-gray-500 shrink-0">2.</span>
                      <span>{t('hlSetup.depositStep2')}</span>
                    </li>
                    <li className="flex gap-2">
                      <span className="text-gray-500 shrink-0">3.</span>
                      <span>{t('hlSetup.depositStep3')}</span>
                    </li>
                  </ol>
                </div>
              </div>
              <a
                href={referralDiag.deposit_url}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center justify-between gap-2 px-3.5 py-2.5 rounded-lg bg-emerald-500/10 border border-emerald-500/30 hover:bg-emerald-500/15 hover:border-emerald-500/50 transition-all group"
              >
                <span className="text-xs font-mono text-emerald-300 truncate">
                  {referralDiag.deposit_url.replace('https://', '')}
                </span>
                <ExternalLink className="w-3.5 h-3.5 shrink-0 text-emerald-400" />
              </a>
            </div>
          )}

          {referralDiag.required_action === 'ENTER_CODE_MANUALLY' && (
            <div className="p-4 space-y-3">
              <div className="flex items-start gap-2.5">
                <div className="w-7 h-7 rounded-lg bg-amber-500/15 border border-amber-500/30 flex items-center justify-center shrink-0">
                  <Info className="w-3.5 h-3.5 text-amber-400" />
                </div>
                <div className="flex-1 min-w-0 pt-0.5">
                  <div className="text-sm font-semibold text-amber-300 mb-2">
                    {t('hlSetup.enterCodeStepTitle')}
                  </div>
                  <ol className="space-y-1.5 text-xs text-gray-300 leading-relaxed">
                    <li className="flex gap-2">
                      <span className="text-gray-500 shrink-0">1.</span>
                      <span>{t('hlSetup.enterCodeStep1')}</span>
                    </li>
                    <li className="flex gap-2">
                      <span className="text-gray-500 shrink-0">2.</span>
                      <span>{t('hlSetup.enterCodeStep2', { code: referralDiag.referral_code })}</span>
                    </li>
                    <li className="flex gap-2">
                      <span className="text-gray-500 shrink-0">3.</span>
                      <span>{t('hlSetup.enterCodeStep3')}</span>
                    </li>
                  </ol>
                </div>
              </div>
              <a
                href={referralDiag.enter_code_url}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center justify-between gap-2 px-3.5 py-2.5 rounded-lg bg-emerald-500/10 border border-emerald-500/30 hover:bg-emerald-500/15 hover:border-emerald-500/50 transition-all group"
              >
                <span className="text-xs font-mono text-emerald-300 truncate">
                  {referralDiag.enter_code_url.replace('https://', '')}
                </span>
                <ExternalLink className="w-3.5 h-3.5 shrink-0 text-emerald-400" />
              </a>
            </div>
          )}

          {referralDiag.required_action === 'WRONG_REFERRER' && (
            <div className="p-4 flex items-start gap-2.5">
              <div className="w-7 h-7 rounded-lg bg-red-500/15 border border-red-500/30 flex items-center justify-center shrink-0">
                <Info className="w-3.5 h-3.5 text-red-400" />
              </div>
              <p className="text-xs text-gray-300 leading-relaxed flex-1 pt-0.5">
                {t('hlSetup.wrongReferrerHint')}
              </p>
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
