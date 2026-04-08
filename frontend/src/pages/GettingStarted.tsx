import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import api from '../api/client'
import { useToastStore } from '../stores/toastStore'
import { useAuthStore } from '../stores/authStore'
import {
  KeyRound,
  Layers,
  Bot,
  ArrowRight,
  ChevronDown,
  ChevronUp,
  Lightbulb,
  Gauge,
  Server,
  Zap,
  Play,
  BarChart3,
  ArrowRightCircle,
  Activity,
  Target,
  AlertTriangle,
  ExternalLink,
  UserCheck,
  ShieldCheck,
  BookOpen,
} from 'lucide-react'
import { ExchangeIcon } from '../components/ui/ExchangeLogo'
import GuidedTour, { TourHelpButton, type TourStep } from '../components/ui/GuidedTour'

/* ─── Prerequisite Banner ─────────────────────────────────────────── */

function PrerequisiteBanner() {
  const { t } = useTranslation()
  const isAdmin = useAuthStore((s) => s.user?.role === 'admin')
  const [affiliateUrls, setAffiliateUrls] = useState<Record<string, string>>({})

  useEffect(() => {
    api.get('/affiliate-links').then((res) => {
      const urls: Record<string, string> = {}
      for (const link of res.data) {
        if (link.affiliate_url) urls[link.exchange_type] = link.affiliate_url
      }
      setAffiliateUrls(urls)
    }).catch((err) => { console.error('Failed to load affiliate links:', err); useToastStore.getState().addToast('error', t('common.loadError', 'Failed to load data')) })
  }, [])

  // Admins bypass affiliate requirements
  if (isAdmin) return null

  const exchanges = [
    { key: 'bitget', name: 'Bitget', icon: <ExchangeIcon exchange="bitget" size={22} /> },
    { key: 'weex', name: 'Weex', icon: <ExchangeIcon exchange="weex" size={22} /> },
    { key: 'hyperliquid', name: 'Hyperliquid', icon: <ExchangeIcon exchange="hyperliquid" size={22} /> },
    { key: 'bitunix', name: 'Bitunix', icon: <ExchangeIcon exchange="bitunix" size={22} /> },
    { key: 'bingx', name: 'BingX', icon: <ExchangeIcon exchange="bingx" size={22} /> },
  ]

  return (
    <div className="border border-amber-500/30 bg-gradient-to-r from-amber-500/10 to-amber-600/5 rounded-2xl p-3 sm:p-5 mb-6">
      <div className="flex items-start gap-2 sm:gap-3">
        <div className="flex-shrink-0 w-8 h-8 sm:w-10 sm:h-10 rounded-xl bg-amber-500/20 border border-amber-500/30 flex items-center justify-center">
          <AlertTriangle size={16} className="text-amber-400 sm:hidden" />
          <AlertTriangle size={20} className="text-amber-400 hidden sm:block" />
        </div>
        <div className="flex-1">
          <h2 className="text-base sm:text-lg font-bold text-amber-300 mb-1">{t('guide.prereqTitle')}</h2>
          <p className="text-sm sm:text-base text-gray-300 mb-2 sm:mb-3">{t('guide.prereqDesc')}</p>

          <div className="space-y-1.5 sm:space-y-2">
            <div className="flex items-start gap-2">
              <div className="flex-shrink-0 w-5 h-5 sm:w-6 sm:h-6 rounded-full bg-amber-500/20 border border-amber-500/30 flex items-center justify-center text-[10px] sm:text-xs font-bold text-amber-400 mt-0.5">1</div>
              <div>
                <p className="text-sm sm:text-base text-gray-200 font-medium">{t('guide.prereqStep1')}</p>
                <div className="flex flex-wrap gap-1.5 sm:gap-2 mt-1 sm:mt-1.5">
                  {exchanges.map((ex) => {
                    const url = affiliateUrls[ex.key]
                    return url ? (
                      <a key={ex.key} href={url} target="_blank" rel="noopener noreferrer"
                        className="inline-flex items-center gap-1.5 sm:gap-2 px-2 sm:px-3 py-1 sm:py-1.5 bg-white/5 border border-white/10 rounded-lg text-xs sm:text-sm text-gray-300 hover:bg-emerald-500/10 hover:border-emerald-500/30 hover:text-emerald-300 transition-colors cursor-pointer">
                        {ex.icon} <span className="hidden sm:inline">{ex.name}</span> <ExternalLink size={10} />
                      </a>
                    ) : (
                      <span key={ex.key} className="inline-flex items-center gap-1.5 sm:gap-2 px-2 sm:px-3 py-1 sm:py-1.5 bg-white/5 border border-white/10 rounded-lg text-xs sm:text-sm text-gray-500">
                        {ex.icon} <span className="hidden sm:inline">{ex.name}</span>
                      </span>
                    )
                  })}
                </div>
                <p className="text-xs sm:text-sm text-gray-500 mt-1">{t('guide.prereqAffiliateHint')}</p>
              </div>
            </div>
            <div className="flex items-start gap-2">
              <div className="flex-shrink-0 w-5 h-5 sm:w-6 sm:h-6 rounded-full bg-amber-500/20 border border-amber-500/30 flex items-center justify-center text-[10px] sm:text-xs font-bold text-amber-400 mt-0.5">2</div>
              <div>
                <p className="text-sm sm:text-base text-gray-200 font-medium">{t('guide.prereqStep2')}</p>
                <p className="text-xs sm:text-sm text-gray-400 mt-0.5">{t('guide.prereqStep2Hint')}</p>
              </div>
            </div>
            <div className="flex items-start gap-2">
              <div className="flex-shrink-0 w-5 h-5 sm:w-6 sm:h-6 rounded-full bg-amber-500/20 border border-amber-500/30 flex items-center justify-center text-[10px] sm:text-xs font-bold text-amber-400 mt-0.5">3</div>
              <div>
                <p className="text-sm sm:text-base text-gray-200 font-medium">{t('guide.prereqStep3')}</p>
                <p className="text-xs sm:text-sm text-gray-400 mt-0.5">{t('guide.prereqStep3Hint')}</p>
              </div>
            </div>
          </div>

          <Link to="/settings"
            className="inline-flex items-center gap-1.5 mt-2 sm:mt-3 px-3 sm:px-4 py-1.5 sm:py-2 text-xs sm:text-sm font-medium bg-amber-500/20 text-amber-300 rounded-lg hover:bg-amber-500/30 border border-amber-500/20 transition-colors">
            <UserCheck size={14} /> {t('guide.prereqGoToSettings')} <ArrowRight size={12} />
          </Link>
        </div>
      </div>
    </div>
  )
}

/* ─── Section: Quick Start ─────────────────────────────────────────── */

function SectionQuickstart() {
  const { t } = useTranslation()

  const flowSteps = [
    { icon: <KeyRound size={24} className="text-yellow-400" />, label: t('guide.qsStep1'), link: '/settings', color: 'from-yellow-500/20 to-yellow-600/5 border-yellow-500/20' },
    { icon: <Bot size={24} className="text-emerald-400" />, label: t('guide.qsStep2'), link: '/bots', color: 'from-emerald-500/20 to-emerald-600/5 border-emerald-500/20' },
    { icon: <Play size={24} className="text-blue-400" />, label: t('guide.qsStep3'), link: '/bots', color: 'from-blue-500/20 to-blue-600/5 border-blue-500/20' },
    { icon: <BarChart3 size={24} className="text-purple-400" />, label: t('guide.qsStep4'), link: '/performance', color: 'from-purple-500/20 to-purple-600/5 border-purple-500/20' },
  ]

  const howCards = [
    { icon: <KeyRound size={26} className="text-yellow-400" />, title: t('guide.connectTitle'), desc: t('guide.connectDesc'), bullets: [t('guide.connectBullet1'), t('guide.connectBullet2'), t('guide.connectBullet3')], color: 'from-yellow-500/15 to-yellow-600/5 border-yellow-500/20', link: '/settings' },
    { icon: <Bot size={26} className="text-emerald-400" />, title: t('guide.configureTitle'), desc: t('guide.configureDesc'), bullets: [t('guide.configureBullet1'), t('guide.configureBullet2'), t('guide.configureBullet3')], color: 'from-emerald-500/15 to-emerald-600/5 border-emerald-500/20', link: '/bots' },
    { icon: <Play size={26} className="text-blue-400" />, title: t('guide.tradeTitle'), desc: t('guide.tradeDesc'), bullets: [t('guide.tradeBullet1'), t('guide.tradeBullet2'), t('guide.tradeBullet3')], color: 'from-blue-500/15 to-blue-600/5 border-blue-500/20', link: '/bots' },
  ]

  return (
    <div className="space-y-8">
      {/* Quick Start Flow */}
      <div data-tour="guide-quickstart">
        <div className="border border-primary-500/20 bg-gradient-to-br from-primary-900/20 to-transparent rounded-2xl p-6">
          <div className="flex items-center gap-2 mb-1">
            <Zap size={22} className="text-primary-400" />
            <h2 className="text-xl font-bold text-white">{t('guide.qsTitle')}</h2>
          </div>
          <p className="text-base text-gray-400 mb-5">{t('guide.qsSubtitle')}</p>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            {flowSteps.map((step, i) => (
              <Link key={i} to={step.link}
                className={`relative flex flex-col items-center text-center p-4 rounded-xl bg-gradient-to-b ${step.color} border hover:scale-[1.02] transition-all duration-200 group`}>
                <div className="absolute -top-2 -left-2 w-6 h-6 rounded-full bg-gray-800 border border-gray-600 flex items-center justify-center text-xs font-bold text-white">{i + 1}</div>
                <div className="mb-2">{step.icon}</div>
                <span className="text-sm font-medium text-gray-200 leading-tight">{step.label}</span>
                {i < flowSteps.length - 1 && <ArrowRightCircle size={16} className="absolute -right-2 top-1/2 -translate-y-1/2 text-gray-600 hidden lg:block" />}
              </Link>
            ))}
          </div>
        </div>
      </div>

      {/* How It Works */}
      <div data-tour="guide-how-it-works">
        <div className="flex items-center gap-2 mb-1">
          <Zap size={22} className="text-primary-400" />
          <h2 className="text-xl font-bold text-white">{t('guide.howItWorksTitle')}</h2>
        </div>
        <p className="text-base text-gray-400 mb-4">{t('guide.howItWorksSubtitle')}</p>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          {howCards.map((card, i) => (
            <Link key={i} to={card.link}
              className={`relative flex flex-col p-4 rounded-xl bg-gradient-to-b ${card.color} border hover:scale-[1.02] transition-all duration-200 group`}>
              <div className="absolute -top-2 -left-2 w-6 h-6 rounded-full bg-gray-800 border border-gray-600 flex items-center justify-center text-xs font-bold text-white">{i + 1}</div>
              <div className="flex items-center gap-2 mb-2">
                {card.icon}
                <h3 className="text-base font-bold text-white">{card.title}</h3>
              </div>
              <p className="text-sm text-gray-400 mb-2">{card.desc}</p>
              <ul className="space-y-1 mt-auto">
                {card.bullets.map((bullet, j) => (
                  <li key={j} className="flex items-center gap-1.5 text-xs text-gray-300">
                    <ArrowRight size={10} className="flex-shrink-0 text-primary-400" />
                    <span>{bullet}</span>
                  </li>
                ))}
              </ul>
            </Link>
          ))}
        </div>
      </div>

      {/* Tip Box */}
      <div className="border border-primary-600/30 bg-white/[0.03] rounded-xl p-5 flex gap-3">
        <Lightbulb size={20} className="flex-shrink-0 text-primary-400 mt-0.5" />
        <div>
          <h3 className="font-semibold text-primary-400 text-base mb-0.5">{t('guide.tipTitle')}</h3>
          <p className="text-gray-300 text-sm">{t('guide.tipText')}</p>
        </div>
      </div>
    </div>
  )
}

/* ─── Section: Step-by-Step Tutorial ──────────────────────────────── */

function SectionTutorial() {
  const { t } = useTranslation()
  const [openStep, setOpenStep] = useState<number | null>(0)

  const steps = [
    { icon: <KeyRound size={20} className="text-yellow-400" />, titleKey: 'step1', color: 'border-yellow-500/30 bg-yellow-500/5' },
    { icon: <Bot size={20} className="text-emerald-400" />, titleKey: 'step2', color: 'border-emerald-500/30 bg-emerald-500/5' },
    { icon: <Gauge size={20} className="text-orange-400" />, titleKey: 'step3', color: 'border-orange-500/30 bg-orange-500/5' },
    { icon: <Play size={20} className="text-blue-400" />, titleKey: 'step4', color: 'border-blue-500/30 bg-blue-500/5' },
    { icon: <BarChart3 size={20} className="text-purple-400" />, titleKey: 'step5', color: 'border-purple-500/30 bg-purple-500/5' },
    { icon: <ShieldCheck size={20} className="text-red-400" />, titleKey: 'step6', color: 'border-red-500/30 bg-red-500/5' },
  ]

  return (
    <div className="space-y-3">
      {steps.map((step, i) => {
        const isOpen = openStep === i
        return (
          <div key={i} className={`border rounded-xl overflow-hidden transition-all ${isOpen ? step.color : 'border-white/10 bg-white/[0.02]'}`}>
            <button
              onClick={() => setOpenStep(isOpen ? null : i)}
              className="w-full flex items-center gap-3 p-4 text-left hover:bg-white/[0.03] transition-colors"
            >
              <div className="flex-shrink-0 w-8 h-8 rounded-lg bg-white/5 flex items-center justify-center text-sm font-bold text-gray-400">
                {i + 1}
              </div>
              {step.icon}
              <div className="flex-1 min-w-0">
                <h3 className="text-base font-semibold text-white">{t(`guide.${step.titleKey}Title`)}</h3>
                <p className="text-sm text-gray-400 truncate">{t(`guide.${step.titleKey}Desc`)}</p>
              </div>
              {isOpen ? <ChevronUp size={16} className="text-gray-400 flex-shrink-0" /> : <ChevronDown size={16} className="text-gray-400 flex-shrink-0" />}
            </button>
            {isOpen && (
              <div className="px-4 pb-4 border-t border-white/5">
                <ol className="space-y-2 mt-3">
                  {[1, 2, 3, 4].map(j => {
                    const text = t(`guide.${step.titleKey}Detail${j}`, '')
                    if (!text) return null
                    return (
                      <li key={j} className="flex items-start gap-2.5 text-sm text-gray-300">
                        <span className="flex-shrink-0 w-5 h-5 rounded-full bg-white/5 border border-white/10 flex items-center justify-center text-xs font-medium text-gray-400 mt-0.5">{j}</span>
                        <span>{text}</span>
                      </li>
                    )
                  })}
                </ol>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

/* ─── Section: Strategies ──────────────────────────────────────────── */

function SectionStrategies() {
  const { t } = useTranslation()

  const strategies = [
    { name: 'Edge Indicator', icon: <Activity size={18} className="text-green-400" />, desc: t('guide.stratEdge'), tf: t('guide.stratEdgeTf'), type: t('guide.stratTypeKline') },
    { name: 'Liquidation Hunter', icon: <Target size={18} className="text-red-400" />, desc: t('guide.stratLiquidation'), tf: t('guide.stratLiquidationTf'), type: t('guide.stratTypeLiq') },
    { name: 'Copy Trading', icon: <Layers size={18} className="text-blue-400" />, desc: t('guide.stratCopy'), tf: t('guide.stratCopyTf'), type: t('guide.stratTypeOnchain') },
  ]

  return (
    <div data-tour="guide-strategies" className="space-y-5">
      <div className="border border-white/10 bg-white/[0.03] rounded-xl p-5">
        <div className="flex items-center gap-2 mb-1">
          <Layers size={20} className="text-blue-400" />
          <h3 className="text-lg font-semibold text-white">{t('guide.stratTitle')}</h3>
        </div>
        <p className="text-sm text-gray-500 mb-4">{t('guide.stratSubtitle')}</p>

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-700">
                <th className="text-left py-2.5 px-3 text-gray-400 font-medium">{t('guide.stratColName')}</th>
                <th className="text-left py-2.5 px-3 text-gray-400 font-medium hidden sm:table-cell">{t('guide.stratColType')}</th>
                <th className="text-left py-2.5 px-3 text-gray-400 font-medium">{t('guide.stratColDesc')}</th>
                <th className="text-left py-2.5 px-3 text-gray-400 font-medium">{t('guide.stratColTf')}</th>
              </tr>
            </thead>
            <tbody>
              {strategies.map((s, i) => (
                <tr key={i} className={i % 2 === 0 ? 'bg-gray-800/30' : ''}>
                  <td className="py-2.5 px-3 font-medium text-gray-200">
                    <span className="inline-flex items-center gap-1.5">{s.icon} {s.name}</span>
                  </td>
                  <td className="py-2.5 px-3 text-gray-400 hidden sm:table-cell">{s.type}</td>
                  <td className="py-2.5 px-3 text-gray-400">{s.desc}</td>
                  <td className="py-2.5 px-3 text-primary-400 font-medium">{s.tf}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Detailed strategy cards */}
      <div>
        <h3 className="text-base font-semibold text-white mb-3 px-1">{t('guide.stratDetailsHeading')}</h3>
        <div className="space-y-4">
          <StrategyCard
            icon={<Activity size={18} className="text-green-400" />}
            title={t('guide.stratEdgeFullTitle')}
            what={t('guide.stratEdgeFullWhat')}
            signalsHeading={t('guide.stratEdgeFullSignals')}
            signals={[
              t('guide.stratEdgeFullSignal1'),
              t('guide.stratEdgeFullSignal2'),
              t('guide.stratEdgeFullSignal3'),
            ]}
            sections={[
              { heading: t('guide.stratEdgeFullExit'), text: t('guide.stratEdgeFullExitText') },
              { text: t('guide.stratEdgeFullProfile') },
            ]}
          />
          <StrategyCard
            icon={<Target size={18} className="text-red-400" />}
            title={t('guide.stratLiquidationFullTitle')}
            what={t('guide.stratLiquidationFullWhat')}
            signalsHeading={t('guide.stratLiquidationFullSignals')}
            signals={[
              t('guide.stratLiquidationFullSignal1'),
              t('guide.stratLiquidationFullSignal2'),
              t('guide.stratLiquidationFullSignal3'),
            ]}
            sections={[
              { heading: t('guide.stratLiquidationFullExit'), text: t('guide.stratLiquidationFullExitText') },
              { text: t('guide.stratLiquidationFullProfile') },
            ]}
          />
          <StrategyCard
            icon={<Layers size={18} className="text-blue-400" />}
            title={t('guide.stratCopyFullTitle')}
            what={t('guide.stratCopyFullWhat')}
            sections={[
              { heading: t('guide.stratCopyFullHow'), text: t('guide.stratCopyFullHowText') },
            ]}
            signalsHeading={t('guide.stratCopyFullSignals')}
            signals={[
              t('guide.stratCopyFullSignal1'),
              t('guide.stratCopyFullSignal2'),
              t('guide.stratCopyFullSignal3'),
            ]}
            extraSections={[
              { heading: t('guide.stratCopyFullColdStart'), text: t('guide.stratCopyFullColdStartText') },
              {
                heading: t('guide.stratCopyFullOverrides'),
                bullets: [
                  t('guide.stratCopyFullOverride1'),
                  t('guide.stratCopyFullOverride2'),
                  t('guide.stratCopyFullOverride3'),
                  t('guide.stratCopyFullOverride4'),
                ],
              },
            ]}
          />
        </div>
      </div>
    </div>
  )
}

interface StrategyCardSection {
  heading?: string
  text?: string
  bullets?: string[]
}

interface StrategyCardProps {
  icon: React.ReactNode
  title: string
  what: string
  signalsHeading?: string
  signals?: string[]
  sections?: StrategyCardSection[]
  extraSections?: StrategyCardSection[]
}

function StrategyCard({ icon, title, what, signalsHeading, signals, sections, extraSections }: StrategyCardProps) {
  return (
    <div className="border border-white/10 bg-white/[0.03] rounded-xl p-5">
      <div className="flex items-center gap-2 mb-2">
        {icon}
        <h4 className="text-base font-semibold text-white">{title}</h4>
      </div>
      <p className="text-sm text-gray-300 leading-relaxed mb-3">{what}</p>

      {sections?.map((s, i) => (
        <div key={`s-${i}`} className="mb-3">
          {s.heading && <p className="text-xs font-semibold text-gray-200 uppercase tracking-wider mb-1">{s.heading}</p>}
          {s.text && <p className="text-sm text-gray-400 leading-relaxed">{s.text}</p>}
        </div>
      ))}

      {signals && signals.length > 0 && (
        <div className="mb-3">
          {signalsHeading && <p className="text-xs font-semibold text-gray-200 uppercase tracking-wider mb-1.5">{signalsHeading}</p>}
          <ul className="space-y-1.5">
            {signals.map((sig, i) => (
              <li key={i} className="text-sm text-gray-400 leading-relaxed pl-4 relative">
                <span className="absolute left-0 top-2 w-1 h-1 rounded-full bg-primary-400" />
                {sig}
              </li>
            ))}
          </ul>
        </div>
      )}

      {extraSections?.map((s, i) => (
        <div key={`e-${i}`} className="mb-3 last:mb-0">
          {s.heading && <p className="text-xs font-semibold text-gray-200 uppercase tracking-wider mb-1">{s.heading}</p>}
          {s.text && <p className="text-sm text-gray-400 leading-relaxed">{s.text}</p>}
          {s.bullets && (
            <ul className="space-y-1 mt-1">
              {s.bullets.map((b, j) => (
                <li key={j} className="text-sm text-gray-400 leading-relaxed pl-4 relative">
                  <span className="absolute left-0 top-2 w-1 h-1 rounded-full bg-gray-500" />
                  {b}
                </li>
              ))}
            </ul>
          )}
        </div>
      ))}
    </div>
  )
}

/* ─── Section: Risk & Config ───────────────────────────────────────── */

function SectionRisk() {
  const { t } = useTranslation()

  const zones = [
    { label: t('guide.riskConservative'), color: '#22c55e', width: '50%' },
    { label: t('guide.riskModerate'), color: '#eab308', width: '50%' },
  ]

  const configItems = [
    t('guide.exampleLeverage'), t('guide.examplePosition'),
    t('guide.exampleSL'), t('guide.exampleTP'),
    t('guide.exampleMaxTrades'), t('guide.exampleLossLimit'),
    t('guide.examplePairs'), t('guide.exampleMode'),
  ]

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
      {/* Risk Gauge */}
      <div className="border border-white/10 bg-white/[0.03] rounded-xl p-5">
        <div className="flex items-center gap-2 mb-2">
          <Gauge size={18} className="text-orange-400" />
          <h4 className="text-base font-semibold text-white">{t('guide.riskTitle')}</h4>
        </div>
        <p className="text-sm text-gray-500 mb-3">{t('guide.riskSubtitle')}</p>
        <div className="flex rounded-lg overflow-hidden h-3 mb-1.5">
          {zones.map((zone, i) => (
            <div key={i} className="h-full transition-all" style={{ width: zone.width, backgroundColor: zone.color, opacity: 0.7 }} />
          ))}
        </div>
        <div className="flex justify-between text-xs text-gray-500 px-0.5">
          {zones.map((zone, i) => <span key={i}>{zone.label}</span>)}
        </div>
        <div className="relative h-2 mt-0.5">
          <div className="absolute left-[16%] -translate-x-1/2 w-0 h-0 border-l-[5px] border-r-[5px] border-b-[6px] border-l-transparent border-r-transparent border-b-emerald-400" />
        </div>
      </div>

      {/* Example Config */}
      <div className="border border-white/10 bg-white/[0.03] rounded-xl p-5">
        <div className="flex items-center gap-2 mb-1">
          <Gauge size={20} className="text-orange-400" />
          <h3 className="text-lg font-semibold text-white">{t('guide.exampleTitle')}</h3>
        </div>
        <p className="text-gray-400 text-sm mb-3">{t('guide.exampleDesc')}</p>
        <div className="grid grid-cols-2 gap-1.5">
          {configItems.map((item, i) => {
            const [label, value] = item.split(': ')
            return (
              <div key={i} className="flex items-center gap-1.5 bg-gray-800/50 rounded px-2.5 py-1.5">
                <span className="text-sm text-gray-400">{label}:</span>
                <span className="text-sm font-medium text-white">{value}</span>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

/* ─── Section: Exchanges ───────────────────────────────────────────── */

function ExchangeSetupCard({ title, steps, icon, defaultOpen = false }: {
  title: string; steps: string[]; icon: React.ReactNode; defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)

  return (
    <div className="border border-white/10 bg-white/[0.03] rounded-xl overflow-hidden">
      <button onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between p-4 text-left hover:bg-white/[0.04] transition-colors">
        <div className="flex items-center gap-2">
          {icon}
          <span className="font-medium text-base text-white">{title}</span>
        </div>
        {open ? <ChevronUp size={16} className="text-gray-400" /> : <ChevronDown size={16} className="text-gray-400" />}
      </button>
      {open && (
        <div className="px-4 pb-4 border-t border-white/5">
          <ol className="space-y-2 mt-2">
            {steps.map((step, i) => (
              <li key={i} className="flex items-start gap-2 text-sm text-gray-300">
                <span className="flex-shrink-0 w-5 h-5 rounded-full bg-gray-700 text-gray-300 flex items-center justify-center text-xs font-medium mt-0.5">{i + 1}</span>
                <span>{step}</span>
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  )
}

function SectionExchanges() {
  const { t } = useTranslation()

  const compRows = [
    { label: t('guide.exchangeCompType'), cex: t('guide.exchangeCompTypeCex'), dex: t('guide.exchangeCompTypeDex') },
    { label: t('guide.exchangeCompCred1'), cex: t('guide.exchangeCompCred1Cex'), dex: t('guide.exchangeCompCred1Dex') },
    { label: t('guide.exchangeCompCred2'), cex: t('guide.exchangeCompCred2Cex'), dex: t('guide.exchangeCompCred2Dex') },
    { label: t('guide.exchangeCompCred3'), cex: t('guide.exchangeCompCred3Cex'), dex: t('guide.exchangeCompCred3Dex') },
    { label: t('guide.exchangeCompDemo'), cex: t('guide.exchangeCompDemoCex'), dex: t('guide.exchangeCompDemoDex') },
    { label: t('guide.exchangeCompSecurity'), cex: t('guide.exchangeCompSecurityCex'), dex: t('guide.exchangeCompSecurityDex') },
  ]

  const setups = [
    { title: t('guide.bitgetSetupTitle'), icon: <ExchangeIcon exchange="bitget" size={24} />, steps: [t('guide.bitgetSetup1'), t('guide.bitgetSetup2'), t('guide.bitgetSetup3'), t('guide.bitgetSetup4')], defaultOpen: true },
    { title: t('guide.weexSetupTitle'), icon: <ExchangeIcon exchange="weex" size={24} />, steps: [t('guide.weexSetup1'), t('guide.weexSetup2'), t('guide.weexSetup3'), t('guide.weexSetup4')] },
    { title: t('guide.hyperliquidSetupTitle'), icon: <ExchangeIcon exchange="hyperliquid" size={24} />, steps: [t('guide.hyperliquidSetup1'), t('guide.hyperliquidSetup2'), t('guide.hyperliquidSetup3'), t('guide.hyperliquidSetup4'), t('guide.hyperliquidSetup5'), t('guide.hyperliquidSetup6')] },
    { title: t('guide.bitunixSetupTitle'), icon: <ExchangeIcon exchange="bitunix" size={24} />, steps: [t('guide.bitunixSetup1'), t('guide.bitunixSetup2'), t('guide.bitunixSetup3'), t('guide.bitunixSetup4')] },
    { title: t('guide.bingxSetupTitle'), icon: <ExchangeIcon exchange="bingx" size={24} />, steps: [t('guide.bingxSetup1'), t('guide.bingxSetup2'), t('guide.bingxSetup3'), t('guide.bingxSetup4')] },
  ]

  return (
    <div data-tour="guide-exchanges" className="space-y-5">
      {/* Comparison Table */}
      <div className="border border-white/10 bg-white/[0.03] rounded-xl p-5">
        <div className="flex items-center gap-2 mb-1">
          <Server size={20} className="text-cyan-400" />
          <h3 className="text-lg font-semibold text-white">{t('guide.exchangeCompTitle')}</h3>
        </div>
        <p className="text-gray-400 text-sm mb-3">{t('guide.exchangeCompSubtitle')}</p>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-700">
                <th className="text-left py-2 px-2 text-gray-400 font-medium">{t('guide.exchangeCompField')}</th>
                <th className="text-left py-2 px-2 text-yellow-400 font-medium">
                  <span className="inline-flex items-center gap-1.5">
                    <ExchangeIcon exchange="bitget" size={20} /> / <ExchangeIcon exchange="weex" size={20} /> / <ExchangeIcon exchange="bitunix" size={20} /> / <ExchangeIcon exchange="bingx" size={20} />
                  </span>
                </th>
                <th className="text-left py-2 px-2 text-green-400 font-medium">
                  <span className="inline-flex items-center gap-1.5"><ExchangeIcon exchange="hyperliquid" size={20} /> HL</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {compRows.map((row, i) => (
                <tr key={i} className={i % 2 === 0 ? 'bg-gray-800/30' : ''}>
                  <td className="py-2 px-2 text-gray-300 font-medium">{row.label}</td>
                  <td className="py-2 px-2 text-gray-300">{row.cex}</td>
                  <td className="py-2 px-2 text-gray-300">{row.dex}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Feature Matrix */}
      <div className="border border-white/10 bg-white/[0.03] rounded-xl p-4 sm:p-5">
        <div className="flex items-center gap-2 mb-1">
          <Activity size={20} className="text-emerald-400" />
          <h3 className="text-lg font-semibold text-white">{t('guide.featureMatrixTitle')}</h3>
        </div>
        <p className="text-gray-400 text-sm mb-3">{t('guide.featureMatrixSubtitle')}</p>
        <div className="overflow-x-auto -mx-4 sm:mx-0 px-4 sm:px-0">
          <table className="w-full text-sm min-w-[480px]">
            <thead>
              <tr className="border-b border-gray-700">
                <th className="text-left py-2.5 pr-2 text-gray-400 font-medium text-xs">{t('guide.featureMatrixFeature')}</th>
                {['bitget', 'weex', 'bingx', 'bitunix', 'hyperliquid'].map(ex => (
                  <th key={ex} className="py-2.5 w-[60px] sm:w-[72px]">
                    <div className="flex items-center justify-center">
                      <ExchangeIcon exchange={ex} size={20} />
                    </div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {/* values order: bitget, weex, bingx, bitunix, hyperliquid */}
              {/* true = ✓, false = ✗, 'partial' = ~ */}
              {([
                { key: 'trading', values: [true, true, true, true, true] },
                { key: 'tpsl', values: [true, true, true, true, true] },
                { key: 'trailingNative', values: [true, false, true, false, false] },
                { key: 'trailingSoftware', values: [true, true, true, true, true] },
                { key: 'feeTracking', values: [true, true, true, true, true] },
                { key: 'fundingFees', values: [true, true, true, 'partial', true] },
                { key: 'marginModes', values: [true, true, true, 'partial', true] },
                { key: 'websocket', values: [true, true, true, true, true] },
                { key: 'demo', values: [true, true, true, 'partial', true] },
              ] as { key: string; values: (boolean | string)[] }[]).map((row, i) => (
                <tr key={row.key} className={i % 2 === 0 ? 'bg-gray-800/30' : ''}>
                  <td className="py-2 pr-2 text-gray-300 font-medium text-xs whitespace-nowrap">{t(`guide.fm_${row.key}`)}</td>
                  {row.values.map((v, j) => (
                    <td key={j} className="py-2">
                      <div className="flex items-center justify-center">
                        {v === true
                          ? <span className="text-emerald-400 text-base leading-none">&#10003;</span>
                          : v === 'partial'
                          ? <span className="text-yellow-400 text-base leading-none">~</span>
                          : <span className="text-gray-600 text-base leading-none">&#10005;</span>}
                      </div>
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="mt-4 space-y-2 border-t border-white/[0.06] pt-3">
          <p className="text-xs text-gray-300 flex items-start gap-2">
            <span className="text-emerald-400 text-sm font-bold mt-px shrink-0">&#10003;</span>
            <span>{t('guide.fm_legendFull')}</span>
          </p>
          <p className="text-xs text-gray-300 flex items-start gap-2">
            <span className="text-yellow-400 text-sm font-bold mt-px shrink-0">~</span>
            <span>{t('guide.fm_legendPartial')}</span>
          </p>
          <p className="text-xs text-gray-300 flex items-start gap-2">
            <span className="text-gray-600 text-sm font-bold mt-px shrink-0">&#10005;</span>
            <span>{t('guide.fm_legendNone')}</span>
          </p>
        </div>
        <div className="mt-3 space-y-2 border-t border-white/[0.06] pt-3">
          <p className="text-xs text-gray-300 flex items-start gap-2">
            <span className="text-emerald-400 text-sm font-bold mt-px shrink-0">&#10003;</span>
            <span><span className="text-emerald-400 font-semibold">{t('guide.fm_trailingNative')}:</span> {t('guide.fm_noteTrailingNative')}</span>
          </p>
          <p className="text-xs text-gray-300 flex items-start gap-2">
            <span className="text-yellow-400 text-sm font-bold mt-px shrink-0">&#10003;</span>
            <span><span className="text-yellow-400 font-semibold">{t('guide.fm_trailingSoftware')}:</span> {t('guide.fm_noteTrailingSoftware')}</span>
          </p>
        </div>
      </div>

      {/* Setup Cards */}
      <div>
        <h2 className="text-base font-semibold text-white mb-2 flex items-center gap-2">
          <KeyRound size={18} className="text-yellow-400" />
          {t('guide.exchangeSetupTitle')}
        </h2>
        <div className="space-y-2">
          {setups.map((setup) => <ExchangeSetupCard key={setup.title} {...setup} />)}
        </div>
      </div>
    </div>
  )
}

/* ─── Section: Security ────────────────────────────────────────────── */

function SectionSecurity() {
  const { t } = useTranslation()

  const details = [1, 2, 3, 4].map(i => t(`guide.step6Detail${i}`, ''))

  return (
    <div className="space-y-5">
      <div className="border border-red-500/20 bg-red-500/5 rounded-xl p-5">
        <div className="flex items-center gap-2 mb-1">
          <ShieldCheck size={20} className="text-red-400" />
          <h3 className="text-lg font-semibold text-white">{t('guide.step6Title')}</h3>
        </div>
        <p className="text-sm text-gray-400 mb-4">{t('guide.step6Desc')}</p>
        <ul className="space-y-3">
          {details.filter(Boolean).map((detail, i) => (
            <li key={i} className="flex items-start gap-3 text-sm text-gray-300">
              <div className="flex-shrink-0 w-6 h-6 rounded-full bg-red-500/10 border border-red-500/20 flex items-center justify-center mt-0.5">
                <ShieldCheck size={12} className="text-red-400" />
              </div>
              <span>{detail}</span>
            </li>
          ))}
        </ul>
      </div>

      {/* Tip Box */}
      <div className="border border-primary-600/30 bg-white/[0.03] rounded-xl p-5 flex gap-3">
        <Lightbulb size={20} className="flex-shrink-0 text-primary-400 mt-0.5" />
        <div>
          <h3 className="font-semibold text-primary-400 text-base mb-0.5">{t('guide.tipTitle')}</h3>
          <p className="text-gray-300 text-sm">{t('guide.tipText')}</p>
        </div>
      </div>
    </div>
  )
}

/* ─── Tour Steps ──────────────────────────────────────────────────── */

const guideTourSteps: TourStep[] = [
  { target: '[data-tour="guide-prereq"]', titleKey: 'tour.guidePrereqTitle', descriptionKey: 'tour.guidePrereqDesc', position: 'bottom' },
  { target: '[data-tour="guide-quickstart"]', titleKey: 'tour.guideQuickstartTitle', descriptionKey: 'tour.guideQuickstartDesc', position: 'bottom' },
  { target: '[data-tour="guide-how-it-works"]', titleKey: 'tour.guideHowItWorksTitle', descriptionKey: 'tour.guideHowItWorksDesc', position: 'bottom' },
  { target: '[data-tour="guide-strategies"]', titleKey: 'tour.guideStrategiesTitle', descriptionKey: 'tour.guideStrategiesDesc', position: 'top' },
  { target: '[data-tour="guide-exchanges"]', titleKey: 'tour.guideExchangesTitle', descriptionKey: 'tour.guideExchangesDesc', position: 'top' },
]

/* ─── Navigation Sections ─────────────────────────────────────────── */

const SECTIONS = [
  { key: 'quickstart', icon: Zap, colorClass: 'text-primary-400' },
  { key: 'tutorial', icon: BookOpen, colorClass: 'text-blue-400' },
  { key: 'strategies', icon: Layers, colorClass: 'text-violet-400' },
  { key: 'risk', icon: Gauge, colorClass: 'text-orange-400' },
  { key: 'exchanges', icon: Server, colorClass: 'text-cyan-400' },
  { key: 'security', icon: ShieldCheck, colorClass: 'text-red-400' },
] as const

/* ─── Main Page ────────────────────────────────────────────────────── */

export default function GettingStarted() {
  const { t } = useTranslation()
  const [activeSection, setActiveSection] = useState<string>('quickstart')

  const renderSection = () => {
    switch (activeSection) {
      case 'quickstart': return <SectionQuickstart />
      case 'tutorial': return <SectionTutorial />
      case 'strategies': return <SectionStrategies />
      case 'risk': return <SectionRisk />
      case 'exchanges': return <SectionExchanges />
      case 'security': return <SectionSecurity />
      default: return <SectionQuickstart />
    }
  }

  return (
    <div className="animate-in">
      {/* Header */}
      <div className="flex items-center justify-between mb-1">
        <h1 className="text-2xl font-bold text-white">{t('guide.title')}</h1>
        <TourHelpButton tourId="getting-started" />
      </div>
      <p className="text-gray-400 text-base mb-6">{t('guide.subtitle')}</p>

      {/* Prerequisite Banner (always visible) */}
      <div data-tour="guide-prereq">
        <PrerequisiteBanner />
      </div>

      {/* Layout: Sidebar + Content */}
      <div className="flex flex-col lg:flex-row gap-5">
        {/* Navigation — horizontal scroll on mobile, vertical sidebar on desktop */}
        <nav className="lg:w-56 flex-shrink-0">
          {/* Mobile: horizontal tabs */}
          <div className="flex lg:hidden gap-1.5 overflow-x-auto pb-2 -mx-1 px-1 scrollbar-hide">
            {SECTIONS.map((section) => {
              const Icon = section.icon
              const isActive = activeSection === section.key
              return (
                <button
                  key={section.key}
                  onClick={() => setActiveSection(section.key)}
                  className={`flex items-center gap-2 px-3.5 py-2 rounded-xl text-sm font-medium whitespace-nowrap transition-all ${
                    isActive
                      ? 'bg-gradient-to-r from-primary-600/20 to-primary-500/10 text-white border border-primary-500/30 shadow-glow-sm'
                      : 'text-gray-400 bg-white/[0.03] border border-white/5 hover:bg-white/[0.06] hover:text-gray-200'
                  }`}
                >
                  <Icon size={15} className={isActive ? section.colorClass : ''} />
                  {t(`guide.nav${section.key.charAt(0).toUpperCase() + section.key.slice(1)}`)}
                </button>
              )
            })}
          </div>

          {/* Desktop: vertical sidebar */}
          <div className="hidden lg:flex flex-col gap-1 sticky top-6">
            {SECTIONS.map((section) => {
              const Icon = section.icon
              const isActive = activeSection === section.key
              return (
                <button
                  key={section.key}
                  onClick={() => setActiveSection(section.key)}
                  className={`flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-medium text-left transition-all ${
                    isActive
                      ? 'bg-gradient-to-r from-primary-600/20 to-primary-500/10 text-white border border-primary-500/30 shadow-glow-sm'
                      : 'text-gray-400 hover:bg-white/[0.04] hover:text-gray-200 border border-transparent'
                  }`}
                >
                  <Icon size={18} className={isActive ? section.colorClass : 'text-gray-500'} />
                  {t(`guide.nav${section.key.charAt(0).toUpperCase() + section.key.slice(1)}`)}
                </button>
              )
            })}
          </div>
        </nav>

        {/* Content */}
        <div className="flex-1 min-w-0">
          {renderSection()}
        </div>
      </div>

      {/* Guided Tour */}
      <GuidedTour tourId="getting-started" steps={guideTourSteps} />
    </div>
  )
}
