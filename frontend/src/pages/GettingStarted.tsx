import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  KeyRound,
  Layers,
  Bot,
  Settings,
  FileText,
  Shield,
  ArrowRight,
  ChevronDown,
  ChevronUp,
  Lightbulb,
  Gauge,
  Server,
} from 'lucide-react'
import { ExchangeIcon } from '../components/ui/ExchangeLogo'

interface StepProps {
  number: number
  icon: React.ReactNode
  title: string
  description: string
  details: string[]
  isLast?: boolean
}

function Step({ number, icon, title, description, details, isLast }: StepProps) {
  return (
    <div className="flex gap-4">
      {/* Timeline */}
      <div className="flex flex-col items-center">
        <div className="flex-shrink-0 w-10 h-10 rounded-full bg-primary-600/20 border-2 border-primary-500 text-primary-400 flex items-center justify-center font-bold text-lg">
          {number}
        </div>
        {!isLast && (
          <div className="w-0.5 flex-1 bg-gradient-to-b from-primary-500/50 to-primary-500/10 my-2" />
        )}
      </div>

      {/* Content */}
      <div className="flex-1 pb-8">
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-5 hover:border-gray-700 transition-colors">
          <div className="flex items-center gap-2 mb-2">
            {icon}
            <h3 className="text-lg font-semibold text-white">{title}</h3>
          </div>
          <p className="text-gray-400 mb-3">{description}</p>
          <ul className="space-y-1.5">
            {details.map((detail, i) => (
              <li key={i} className="flex items-start gap-2 text-sm text-gray-300">
                <ArrowRight size={14} className="flex-shrink-0 mt-0.5 text-primary-400" />
                <span>{detail}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  )
}

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
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-6">
      <div className="flex items-center gap-2 mb-1">
        <Server size={20} className="text-cyan-400" />
        <h3 className="text-lg font-semibold text-white">{t('guide.exchangeCompTitle')}</h3>
      </div>
      <p className="text-gray-400 text-sm mb-4">{t('guide.exchangeCompSubtitle')}</p>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-700">
              <th className="text-left py-2.5 px-3 text-gray-400 font-medium">{t('guide.exchangeCompField')}</th>
              <th className="text-left py-2.5 px-3 text-yellow-400 font-medium">
                <span className="inline-flex items-center gap-2">
                  <ExchangeIcon exchange="bitget" size={16} />
                  <span>/</span>
                  <ExchangeIcon exchange="weex" size={16} />
                </span>
              </th>
              <th className="text-left py-2.5 px-3 text-green-400 font-medium">
                <span className="inline-flex items-center gap-1.5">
                  <ExchangeIcon exchange="hyperliquid" size={16} />
                  <span>Hyperliquid</span>
                </span>
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i} className={i % 2 === 0 ? 'bg-gray-800/30' : ''}>
                <td className="py-2.5 px-3 text-gray-300 font-medium">{row.label}</td>
                <td className="py-2.5 px-3 text-gray-300">{row.cex}</td>
                <td className="py-2.5 px-3 text-gray-300">{row.dex}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

interface ExchangeSetupProps {
  title: string
  steps: string[]
  icon: React.ReactNode
  borderColor: string
}

function ExchangeSetupCard({ title, steps, icon, borderColor }: ExchangeSetupProps) {
  const [open, setOpen] = useState(false)

  return (
    <div className={`bg-gray-900 border rounded-lg overflow-hidden ${borderColor}`}>
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between p-4 text-left hover:bg-gray-800/50 transition-colors"
      >
        <div className="flex items-center gap-2">
          {icon}
          <span className="font-semibold text-white">{title}</span>
        </div>
        {open ? <ChevronUp size={18} className="text-gray-400" /> : <ChevronDown size={18} className="text-gray-400" />}
      </button>
      {open && (
        <div className="px-4 pb-4 border-t border-gray-800">
          <ol className="space-y-2 mt-3">
            {steps.map((step, i) => (
              <li key={i} className="flex items-start gap-3 text-sm text-gray-300">
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
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-6">
      <div className="flex items-center gap-2 mb-1">
        <Gauge size={20} className="text-orange-400" />
        <h3 className="text-lg font-semibold text-white">{t('guide.exampleTitle')}</h3>
      </div>
      <p className="text-gray-400 text-sm mb-4">{t('guide.exampleDesc')}</p>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        {items.map((item, i) => {
          const [label, value] = item.split(': ')
          return (
            <div key={i} className="flex items-center gap-2 bg-gray-800/50 rounded px-3 py-2">
              <span className="text-sm text-gray-400">{label}:</span>
              <span className="text-sm font-medium text-white">{value}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default function GettingStarted() {
  const { t } = useTranslation()

  const steps: StepProps[] = [
    {
      number: 1,
      icon: <KeyRound size={20} className="text-yellow-400" />,
      title: t('guide.step1Title'),
      description: t('guide.step1Desc'),
      details: [
        t('guide.step1Detail1'),
        t('guide.step1Detail2'),
        t('guide.step1Detail3'),
        t('guide.step1Detail4'),
      ],
    },
    {
      number: 2,
      icon: <Layers size={20} className="text-blue-400" />,
      title: t('guide.step2Title'),
      description: t('guide.step2Desc'),
      details: [
        t('guide.step2Detail1'),
        t('guide.step2Detail2'),
        t('guide.step2Detail3'),
        t('guide.step2Detail4'),
      ],
    },
    {
      number: 3,
      icon: <Settings size={20} className="text-gray-400" />,
      title: t('guide.step3Title'),
      description: t('guide.step3Desc'),
      details: [
        t('guide.step3Detail1'),
        t('guide.step3Detail2'),
        t('guide.step3Detail3'),
        t('guide.step3Detail4'),
      ],
    },
    {
      number: 4,
      icon: <Bot size={20} className="text-green-400" />,
      title: t('guide.step4Title'),
      description: t('guide.step4Desc'),
      details: [
        t('guide.step4Detail1'),
        t('guide.step4Detail2'),
        t('guide.step4Detail3'),
        t('guide.step4Detail4'),
      ],
    },
    {
      number: 5,
      icon: <FileText size={20} className="text-purple-400" />,
      title: t('guide.step5Title'),
      description: t('guide.step5Desc'),
      details: [
        t('guide.step5Detail1'),
        t('guide.step5Detail2'),
        t('guide.step5Detail3'),
      ],
    },
    {
      number: 6,
      icon: <Shield size={20} className="text-red-400" />,
      title: t('guide.step6Title'),
      description: t('guide.step6Desc'),
      details: [
        t('guide.step6Detail1'),
        t('guide.step6Detail2'),
        t('guide.step6Detail3'),
        t('guide.step6Detail4'),
      ],
    },
  ]

  const exchangeSetups = [
    {
      title: t('guide.bitgetSetupTitle'),
      icon: <ExchangeIcon exchange="bitget" size={20} />,
      borderColor: 'border-yellow-500/30',
      steps: [
        t('guide.bitgetSetup1'),
        t('guide.bitgetSetup2'),
        t('guide.bitgetSetup3'),
        t('guide.bitgetSetup4'),
      ],
    },
    {
      title: t('guide.weexSetupTitle'),
      icon: <ExchangeIcon exchange="weex" size={20} />,
      borderColor: 'border-blue-500/30',
      steps: [
        t('guide.weexSetup1'),
        t('guide.weexSetup2'),
        t('guide.weexSetup3'),
        t('guide.weexSetup4'),
      ],
    },
    {
      title: t('guide.hyperliquidSetupTitle'),
      icon: <ExchangeIcon exchange="hyperliquid" size={20} />,
      borderColor: 'border-green-500/30',
      steps: [
        t('guide.hyperliquidSetup1'),
        t('guide.hyperliquidSetup2'),
        t('guide.hyperliquidSetup3'),
        t('guide.hyperliquidSetup4'),
        t('guide.hyperliquidSetup5'),
        t('guide.hyperliquidSetup6'),
      ],
    },
  ]

  return (
    <div>
      <h1 className="text-2xl font-bold text-white mb-2">{t('guide.title')}</h1>
      <p className="text-gray-400 mb-8">{t('guide.subtitle')}</p>

      {/* Two-column layout: Steps left, Reference right */}
      <div className="grid grid-cols-1 xl:grid-cols-[1fr_1fr] gap-8 items-start">

        {/* Left Column: Steps Timeline */}
        <div>
          {steps.map((step, i) => (
            <Step key={step.number} {...step} isLast={i === steps.length - 1} />
          ))}
        </div>

        {/* Right Column: Reference Info (sticky on desktop) */}
        <div className="xl:sticky xl:top-4 space-y-5">
          {/* Exchange Comparison Table */}
          <ExchangeComparisonTable />

          {/* Per-Exchange Setup */}
          <div>
            <h2 className="text-lg font-semibold text-white mb-3 flex items-center gap-2">
              <KeyRound size={18} className="text-yellow-400" />
              {t('guide.exchangeSetupTitle')}
            </h2>
            <div className="space-y-3">
              {exchangeSetups.map((setup) => (
                <ExchangeSetupCard key={setup.title} {...setup} />
              ))}
            </div>
          </div>

          {/* Example Configuration */}
          <ExampleConfig />

          {/* Tip Box */}
          <div className="bg-gray-900 border border-primary-600/30 rounded-lg p-5 flex gap-3">
            <Lightbulb size={20} className="flex-shrink-0 text-primary-400 mt-0.5" />
            <div>
              <h3 className="font-semibold text-primary-400 mb-1">{t('guide.tipTitle')}</h3>
              <p className="text-gray-300 text-sm">{t('guide.tipText')}</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
