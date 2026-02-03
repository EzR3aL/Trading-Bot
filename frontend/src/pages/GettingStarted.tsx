import { useTranslation } from 'react-i18next'
import {
  KeyRound,
  Layers,
  Bot,
  Settings,
  FileText,
  Shield,
  ArrowRight,
} from 'lucide-react'

interface StepProps {
  number: number
  icon: React.ReactNode
  title: string
  description: string
  details: string[]
}

function Step({ number, icon, title, description, details }: StepProps) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-6">
      <div className="flex items-start gap-4">
        <div className="flex-shrink-0 w-10 h-10 rounded-full bg-primary-600/20 text-primary-400 flex items-center justify-center font-bold text-lg">
          {number}
        </div>
        <div className="flex-1">
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
      ],
    },
  ]

  return (
    <div>
      <h1 className="text-2xl font-bold text-white mb-2">{t('guide.title')}</h1>
      <p className="text-gray-400 mb-8">{t('guide.subtitle')}</p>

      <div className="space-y-4">
        {steps.map((step) => (
          <Step key={step.number} {...step} />
        ))}
      </div>

      <div className="mt-8 bg-gray-900 border border-primary-600/30 rounded-lg p-6">
        <h3 className="text-lg font-semibold text-primary-400 mb-2">{t('guide.tipTitle')}</h3>
        <p className="text-gray-300 text-sm">{t('guide.tipText')}</p>
      </div>
    </div>
  )
}
