import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import api from '../api/client'
import { useToastStore } from '../stores/toastStore'
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
  TrendingUp,
  Brain,
  Activity,
  Target,
  AlertTriangle,
  ExternalLink,
  UserCheck,
} from 'lucide-react'
import { ExchangeIcon } from '../components/ui/ExchangeLogo'
import GuidedTour, { TourHelpButton, type TourStep } from '../components/ui/GuidedTour'

/* ─── Prerequisite Banner ─────────────────────────────────────────── */

function PrerequisiteBanner() {
  const { t } = useTranslation()
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

  const exchanges = [
    { key: 'bitget', name: 'Bitget', icon: <ExchangeIcon exchange="bitget" size={22} /> },
    { key: 'weex', name: 'Weex', icon: <ExchangeIcon exchange="weex" size={22} /> },
    { key: 'hyperliquid', name: 'Hyperliquid', icon: <ExchangeIcon exchange="hyperliquid" size={22} /> },
  ]

  return (
    <div className="border border-amber-500/30 bg-gradient-to-r from-amber-500/10 to-amber-600/5 rounded-2xl p-5 mb-6">
      <div className="flex items-start gap-3">
        <div className="flex-shrink-0 w-10 h-10 rounded-xl bg-amber-500/20 border border-amber-500/30 flex items-center justify-center">
          <AlertTriangle size={20} className="text-amber-400" />
        </div>
        <div className="flex-1">
          <h2 className="text-lg font-bold text-amber-300 mb-1">{t('guide.prereqTitle')}</h2>
          <p className="text-base text-gray-300 mb-3">{t('guide.prereqDesc')}</p>

          <div className="space-y-2">
            {/* Step 1: Register */}
            <div className="flex items-start gap-2">
              <div className="flex-shrink-0 w-6 h-6 rounded-full bg-amber-500/20 border border-amber-500/30 flex items-center justify-center text-xs font-bold text-amber-400 mt-0.5">1</div>
              <div>
                <p className="text-base text-gray-200 font-medium">{t('guide.prereqStep1')}</p>
                <div className="flex flex-wrap gap-2 mt-1.5">
                  {exchanges.map((ex) => {
                    const url = affiliateUrls[ex.key]
                    return url ? (
                      <a
                        key={ex.key}
                        href={url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-2 px-3 py-1.5 bg-white/5 border border-white/10 rounded-lg text-sm text-gray-300 hover:bg-emerald-500/10 hover:border-emerald-500/30 hover:text-emerald-300 transition-colors cursor-pointer"
                      >
                        {ex.icon}
                        <span>{ex.name}</span>
                        <ExternalLink size={10} />
                      </a>
                    ) : (
                      <span key={ex.key} className="inline-flex items-center gap-2 px-3 py-1.5 bg-white/5 border border-white/10 rounded-lg text-sm text-gray-500">
                        {ex.icon}
                        <span>{ex.name}</span>
                      </span>
                    )
                  })}
                </div>
                <p className="text-sm text-gray-500 mt-1">{t('guide.prereqAffiliateHint')}</p>
              </div>
            </div>

            {/* Step 2: API Keys */}
            <div className="flex items-start gap-2">
              <div className="flex-shrink-0 w-6 h-6 rounded-full bg-amber-500/20 border border-amber-500/30 flex items-center justify-center text-xs font-bold text-amber-400 mt-0.5">2</div>
              <div>
                <p className="text-base text-gray-200 font-medium">{t('guide.prereqStep2')}</p>
                <p className="text-sm text-gray-400 mt-0.5">{t('guide.prereqStep2Hint')}</p>
              </div>
            </div>

            {/* Step 3: UID */}
            <div className="flex items-start gap-2">
              <div className="flex-shrink-0 w-6 h-6 rounded-full bg-amber-500/20 border border-amber-500/30 flex items-center justify-center text-xs font-bold text-amber-400 mt-0.5">3</div>
              <div>
                <p className="text-base text-gray-200 font-medium">{t('guide.prereqStep3')}</p>
                <p className="text-sm text-gray-400 mt-0.5">{t('guide.prereqStep3Hint')}</p>
              </div>
            </div>
          </div>

          <Link
            to="/settings"
            className="inline-flex items-center gap-1.5 mt-3 px-4 py-2 text-sm font-medium bg-amber-500/20 text-amber-300 rounded-lg hover:bg-amber-500/30 border border-amber-500/20 transition-colors"
          >
            <UserCheck size={14} />
            {t('guide.prereqGoToSettings')}
            <ArrowRight size={12} />
          </Link>
        </div>
      </div>
    </div>
  )
}

/* ─── Quick-Start Flow ──────────────────────────────────────────────── */

function QuickStartFlow() {
  const { t } = useTranslation()

  const flowSteps = [
    {
      icon: <KeyRound size={24} className="text-yellow-400" />,
      label: t('guide.qsStep1'),
      link: '/settings',
      color: 'from-yellow-500/20 to-yellow-600/5 border-yellow-500/20',
    },
    {
      icon: <Bot size={24} className="text-emerald-400" />,
      label: t('guide.qsStep2'),
      link: '/bots',
      color: 'from-emerald-500/20 to-emerald-600/5 border-emerald-500/20',
    },
    {
      icon: <Play size={24} className="text-blue-400" />,
      label: t('guide.qsStep3'),
      link: '/bots',
      color: 'from-blue-500/20 to-blue-600/5 border-blue-500/20',
    },
    {
      icon: <BarChart3 size={24} className="text-purple-400" />,
      label: t('guide.qsStep4'),
      link: '/performance',
      color: 'from-purple-500/20 to-purple-600/5 border-purple-500/20',
    },
  ]

  return (
    <div className="border border-primary-500/20 bg-gradient-to-br from-primary-900/20 to-transparent rounded-2xl p-6 mb-8">
      <div className="flex items-center gap-2 mb-1">
        <Zap size={22} className="text-primary-400" />
        <h2 className="text-xl font-bold text-white">{t('guide.qsTitle')}</h2>
      </div>
      <p className="text-base text-gray-400 mb-5">{t('guide.qsSubtitle')}</p>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {flowSteps.map((step, i) => (
          <Link
            key={i}
            to={step.link}
            className={`relative flex flex-col items-center text-center p-4 rounded-xl bg-gradient-to-b ${step.color} border hover:scale-[1.02] transition-all duration-200 group`}
          >
            {/* Step number badge */}
            <div className="absolute -top-2 -left-2 w-6 h-6 rounded-full bg-gray-800 border border-gray-600 flex items-center justify-center text-xs font-bold text-white">
              {i + 1}
            </div>
            <div className="mb-2">{step.icon}</div>
            <span className="text-sm font-medium text-gray-200 leading-tight">{step.label}</span>
            {i < flowSteps.length - 1 && (
              <ArrowRightCircle size={16} className="absolute -right-2 top-1/2 -translate-y-1/2 text-gray-600 hidden lg:block" />
            )}
          </Link>
        ))}
      </div>
    </div>
  )
}

/* ─── Strategy Overview Table ──────────────────────────────────────── */

function StrategyOverview() {
  const { t } = useTranslation()

  const strategies = [
    { name: 'KI-Companion', icon: <Brain size={18} className="text-violet-400" />, desc: t('guide.stratKi'), tf: t('guide.stratKiTf'), type: t('guide.stratTypeKi') },
    { name: 'Sentiment Surfer', icon: <TrendingUp size={18} className="text-cyan-400" />, desc: t('guide.stratSentiment'), tf: t('guide.stratSentimentTf'), type: t('guide.stratTypeSentiment') },
    { name: 'Liquidation Hunter', icon: <Target size={18} className="text-red-400" />, desc: t('guide.stratLiquidation'), tf: t('guide.stratLiquidationTf'), type: t('guide.stratTypeLiq') },
    { name: 'Degen', icon: <Zap size={18} className="text-amber-400" />, desc: t('guide.stratDegen'), tf: t('guide.stratDegenTf'), type: t('guide.stratTypeKi') },
    { name: 'Edge Indicator', icon: <Activity size={18} className="text-green-400" />, desc: t('guide.stratEdge'), tf: t('guide.stratEdgeTf'), type: t('guide.stratTypeKline') },
    { name: 'Claude-Edge', icon: <Activity size={18} className="text-emerald-400" />, desc: t('guide.stratClaudeEdge'), tf: t('guide.stratClaudeEdgeTf'), type: t('guide.stratTypeKline') },
  ]

  return (
    <div className="border border-white/10 bg-white/[0.03] rounded-xl p-5 h-full flex flex-col">
      <div className="flex items-center gap-2 mb-1">
        <Layers size={20} className="text-blue-400" />
        <h3 className="text-lg font-semibold text-white">{t('guide.stratTitle')}</h3>
      </div>
      <p className="text-sm text-gray-500 mb-3">{t('guide.stratSubtitle')}</p>

      <div className="overflow-x-auto flex-1">
        <table className="w-full text-sm h-full">
          <thead>
            <tr className="border-b border-gray-700">
              <th className="text-left py-2 px-2 text-gray-400 font-medium">{t('guide.stratColName')}</th>
              <th className="text-left py-2 px-2 text-gray-400 font-medium hidden sm:table-cell">{t('guide.stratColType')}</th>
              <th className="text-left py-2 px-2 text-gray-400 font-medium">{t('guide.stratColDesc')}</th>
              <th className="text-left py-2 px-2 text-gray-400 font-medium">{t('guide.stratColTf')}</th>
            </tr>
          </thead>
          <tbody>
            {strategies.map((s, i) => (
              <tr key={i} className={i % 2 === 0 ? 'bg-gray-800/30' : ''}>
                <td className="py-2 px-2 font-medium text-gray-200">
                  <span className="inline-flex items-center gap-1.5">{s.icon} {s.name}</span>
                </td>
                <td className="py-2 px-2 text-gray-400 hidden sm:table-cell">{s.type}</td>
                <td className="py-2 px-2 text-gray-400">{s.desc}</td>
                <td className="py-2 px-2 text-primary-400 font-medium">{s.tf}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

/* ─── Risk Gauge (inline SVG) ─────────────────────────────────────── */

function RiskGauge() {
  const { t } = useTranslation()

  const zones = [
    { label: t('guide.riskConservative'), color: '#22c55e', width: '33%' },
    { label: t('guide.riskModerate'), color: '#eab308', width: '34%' },
    { label: t('guide.riskAggressive'), color: '#ef4444', width: '33%' },
  ]

  return (
    <div className="mb-4">
      <div className="flex items-center gap-2 mb-2">
        <Gauge size={18} className="text-orange-400" />
        <h4 className="text-base font-semibold text-white">{t('guide.riskTitle')}</h4>
      </div>
      <p className="text-sm text-gray-500 mb-2">{t('guide.riskSubtitle')}</p>
      <div className="flex rounded-lg overflow-hidden h-3 mb-1.5">
        {zones.map((zone, i) => (
          <div
            key={i}
            className="h-full transition-all"
            style={{ width: zone.width, backgroundColor: zone.color, opacity: 0.7 }}
          />
        ))}
      </div>
      <div className="flex justify-between text-xs text-gray-500 px-0.5">
        {zones.map((zone, i) => (
          <span key={i}>{zone.label}</span>
        ))}
      </div>
      {/* Pointer at Conservative */}
      <div className="relative h-2 mt-0.5">
        <div className="absolute left-[16%] -translate-x-1/2 w-0 h-0 border-l-[5px] border-r-[5px] border-b-[6px] border-l-transparent border-r-transparent border-b-emerald-400" />
      </div>
    </div>
  )
}

/* ─── How It Works Cards ──────────────────────────────────────────── */

function HowItWorksCards() {
  const { t } = useTranslation()

  const cards = [
    {
      icon: <KeyRound size={26} className="text-yellow-400" />,
      title: t('guide.connectTitle'),
      desc: t('guide.connectDesc'),
      bullets: [t('guide.connectBullet1'), t('guide.connectBullet2'), t('guide.connectBullet3')],
      color: 'from-yellow-500/15 to-yellow-600/5 border-yellow-500/20',
      link: '/settings',
    },
    {
      icon: <Bot size={26} className="text-emerald-400" />,
      title: t('guide.configureTitle'),
      desc: t('guide.configureDesc'),
      bullets: [t('guide.configureBullet1'), t('guide.configureBullet2'), t('guide.configureBullet3')],
      color: 'from-emerald-500/15 to-emerald-600/5 border-emerald-500/20',
      link: '/bots',
    },
    {
      icon: <Play size={26} className="text-blue-400" />,
      title: t('guide.tradeTitle'),
      desc: t('guide.tradeDesc'),
      bullets: [t('guide.tradeBullet1'), t('guide.tradeBullet2'), t('guide.tradeBullet3')],
      color: 'from-blue-500/15 to-blue-600/5 border-blue-500/20',
      link: '/bots',
    },
  ]

  return (
    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
      {cards.map((card, i) => (
        <Link
          key={i}
          to={card.link}
          className={`relative flex flex-col p-4 rounded-xl bg-gradient-to-b ${card.color} border hover:scale-[1.02] transition-all duration-200 group`}
        >
          <div className="absolute -top-2 -left-2 w-6 h-6 rounded-full bg-gray-800 border border-gray-600 flex items-center justify-center text-xs font-bold text-white">
            {i + 1}
          </div>
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
  )
}

/* ─── Exchange Comparison ──────────────────────────────────────────── */

function ExchangeComparisonTable() {
  const { t } = useTranslation()

  const rows = [
    { label: t('guide.exchangeCompType'), cex: t('guide.exchangeCompTypeCex'), dex: t('guide.exchangeCompTypeDex') },
    { label: t('guide.exchangeCompCred1'), cex: t('guide.exchangeCompCred1Cex'), dex: t('guide.exchangeCompCred1Dex') },
    { label: t('guide.exchangeCompCred2'), cex: t('guide.exchangeCompCred2Cex'), dex: t('guide.exchangeCompCred2Dex') },
    { label: t('guide.exchangeCompCred3'), cex: t('guide.exchangeCompCred3Cex'), dex: t('guide.exchangeCompCred3Dex') },
    { label: t('guide.exchangeCompDemo'), cex: t('guide.exchangeCompDemoCex'), dex: t('guide.exchangeCompDemoDex') },
    { label: t('guide.exchangeCompSecurity'), cex: t('guide.exchangeCompSecurityCex'), dex: t('guide.exchangeCompSecurityDex') },
  ]

  return (
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
                  <ExchangeIcon exchange="bitget" size={20} />
                  <span>/</span>
                  <ExchangeIcon exchange="weex" size={20} />
                </span>
              </th>
              <th className="text-left py-2 px-2 text-green-400 font-medium">
                <span className="inline-flex items-center gap-1.5">
                  <ExchangeIcon exchange="hyperliquid" size={20} />
                  <span>HL</span>
                </span>
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
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
  )
}

/* ─── Exchange Setup Cards ─────────────────────────────────────────── */

interface ExchangeSetupProps {
  title: string
  steps: string[]
  icon: React.ReactNode
  defaultOpen?: boolean
}

function ExchangeSetupCard({ title, steps, icon, defaultOpen = false }: ExchangeSetupProps) {
  const [open, setOpen] = useState(defaultOpen)

  return (
    <div className="border border-white/10 bg-white/[0.03] rounded-xl overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between p-4 text-left hover:bg-white/[0.04] transition-colors"
      >
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
                <span className="flex-shrink-0 w-5 h-5 rounded-full bg-gray-700 text-gray-300 flex items-center justify-center text-xs font-medium mt-0.5">
                  {i + 1}
                </span>
                <span>{step}</span>
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  )
}

/* ─── Example Config ───────────────────────────────────────────────── */

function ExampleConfig() {
  const { t } = useTranslation()

  const items = [
    t('guide.exampleLeverage'),
    t('guide.examplePosition'),
    t('guide.exampleSL'),
    t('guide.exampleTP'),
    t('guide.exampleMaxTrades'),
    t('guide.exampleLossLimit'),
    t('guide.examplePairs'),
    t('guide.exampleMode'),
  ]

  return (
    <div className="border border-white/10 bg-white/[0.03] rounded-xl p-5">
      <div className="flex items-center gap-2 mb-1">
        <Gauge size={20} className="text-orange-400" />
        <h3 className="text-lg font-semibold text-white">{t('guide.exampleTitle')}</h3>
      </div>
      <p className="text-gray-400 text-sm mb-3">{t('guide.exampleDesc')}</p>

      <div className="grid grid-cols-2 gap-1.5">
        {items.map((item, i) => {
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
  )
}

/* ─── Main Page ────────────────────────────────────────────────────── */

/* ─── Tour Steps ──────────────────────────────────────────────────── */

const guideTourSteps: TourStep[] = [
  {
    target: '[data-tour="guide-prereq"]',
    titleKey: 'tour.guidePrereqTitle',
    descriptionKey: 'tour.guidePrereqDesc',
    position: 'bottom',
  },
  {
    target: '[data-tour="guide-quickstart"]',
    titleKey: 'tour.guideQuickstartTitle',
    descriptionKey: 'tour.guideQuickstartDesc',
    position: 'bottom',
  },
  {
    target: '[data-tour="guide-how-it-works"]',
    titleKey: 'tour.guideHowItWorksTitle',
    descriptionKey: 'tour.guideHowItWorksDesc',
    position: 'bottom',
  },
  {
    target: '[data-tour="guide-strategies"]',
    titleKey: 'tour.guideStrategiesTitle',
    descriptionKey: 'tour.guideStrategiesDesc',
    position: 'top',
  },
  {
    target: '[data-tour="guide-exchanges"]',
    titleKey: 'tour.guideExchangesTitle',
    descriptionKey: 'tour.guideExchangesDesc',
    position: 'top',
  },
]

/* ─── Main Page ────────────────────────────────────────────────────── */

export default function GettingStarted() {
  const { t } = useTranslation()

  const exchangeSetups = [
    {
      title: t('guide.bitgetSetupTitle'),
      icon: <ExchangeIcon exchange="bitget" size={24} />,
      steps: [t('guide.bitgetSetup1'), t('guide.bitgetSetup2'), t('guide.bitgetSetup3'), t('guide.bitgetSetup4')],
      defaultOpen: true,
    },
    {
      title: t('guide.weexSetupTitle'),
      icon: <ExchangeIcon exchange="weex" size={24} />,
      steps: [t('guide.weexSetup1'), t('guide.weexSetup2'), t('guide.weexSetup3'), t('guide.weexSetup4')],
    },
    {
      title: t('guide.hyperliquidSetupTitle'),
      icon: <ExchangeIcon exchange="hyperliquid" size={24} />,
      steps: [t('guide.hyperliquidSetup1'), t('guide.hyperliquidSetup2'), t('guide.hyperliquidSetup3'), t('guide.hyperliquidSetup4'), t('guide.hyperliquidSetup5'), t('guide.hyperliquidSetup6')],
    },
  ]

  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <h1 className="text-2xl font-bold text-white">{t('guide.title')}</h1>
        <TourHelpButton tourId="getting-started" />
      </div>
      <p className="text-gray-400 text-base mb-6">{t('guide.subtitle')}</p>

      {/* Prerequisite Info */}
      <div data-tour="guide-prereq">
        <PrerequisiteBanner />
      </div>

      {/* Quick Start Flow */}
      <div data-tour="guide-quickstart">
        <QuickStartFlow />
      </div>

      {/* How It Works */}
      <div data-tour="guide-how-it-works" className="mb-8">
        <div className="flex items-center gap-2 mb-1">
          <Zap size={22} className="text-primary-400" />
          <h2 className="text-xl font-bold text-white">{t('guide.howItWorksTitle')}</h2>
        </div>
        <p className="text-base text-gray-400 mb-4">{t('guide.howItWorksSubtitle')}</p>
        <HowItWorksCards />
      </div>

      {/* Two-column: Strategies + Risk / Example Config */}
      <div data-tour="guide-strategies" className="grid grid-cols-1 xl:grid-cols-2 gap-6 items-stretch mb-8">
        {/* Left: Risk + Example Config */}
        <div className="space-y-4">
          <div className="border border-white/10 bg-white/[0.03] rounded-xl p-5">
            <RiskGauge />
          </div>
          <ExampleConfig />
        </div>

        {/* Right: Strategy Overview */}
        <StrategyOverview />
      </div>

      {/* Exchange Setup */}
      <div data-tour="guide-exchanges" className="space-y-4 mb-8">
        <ExchangeComparisonTable />

        <div>
          <h2 className="text-base font-semibold text-white mb-2 flex items-center gap-2">
            <KeyRound size={18} className="text-yellow-400" />
            {t('guide.exchangeSetupTitle')}
          </h2>
          <div className="space-y-2">
            {exchangeSetups.map((setup) => (
              <ExchangeSetupCard key={setup.title} {...setup} />
            ))}
          </div>
        </div>
      </div>

      {/* Tip Box */}
      <div className="border border-primary-600/30 bg-white/[0.03] rounded-xl p-5 flex gap-3 mb-4">
        <Lightbulb size={20} className="flex-shrink-0 text-primary-400 mt-0.5" />
        <div>
          <h3 className="font-semibold text-primary-400 text-base mb-0.5">{t('guide.tipTitle')}</h3>
          <p className="text-gray-300 text-sm">{t('guide.tipText')}</p>
        </div>
      </div>

      {/* Guided Tour */}
      <GuidedTour tourId="getting-started" steps={guideTourSteps} />
    </div>
  )
}
