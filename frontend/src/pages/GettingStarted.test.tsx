import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import GettingStarted from './GettingStarted'

// Mock react-i18next
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
}))

// Mock ExchangeLogo
vi.mock('../components/ui/ExchangeLogo', () => ({
  ExchangeIcon: ({ exchange }: { exchange: string }) => (
    <span data-testid={`exchange-${exchange}`} />
  ),
}))

function renderPage() {
  return render(
    <MemoryRouter>
      <GettingStarted />
    </MemoryRouter>,
  )
}

describe('GettingStarted', () => {
  describe('page structure', () => {
    it('renders guide.title', () => {
      renderPage()
      expect(screen.getByText('guide.title')).toBeInTheDocument()
    })

    it('renders guide.subtitle', () => {
      renderPage()
      expect(screen.getByText('guide.subtitle')).toBeInTheDocument()
    })
  })

  describe('QuickStartFlow', () => {
    it('renders guide.qsTitle', () => {
      renderPage()
      expect(screen.getByText('guide.qsTitle')).toBeInTheDocument()
    })

    it('renders guide.qsStep1 through qsStep4', () => {
      renderPage()
      expect(screen.getByText('guide.qsStep1')).toBeInTheDocument()
      expect(screen.getByText('guide.qsStep2')).toBeInTheDocument()
      expect(screen.getByText('guide.qsStep3')).toBeInTheDocument()
      expect(screen.getByText('guide.qsStep4')).toBeInTheDocument()
    })

    it('links to /settings, /bots, /performance', () => {
      renderPage()
      const links = screen.getAllByRole('link')
      const hrefs = links.map((l) => l.getAttribute('href'))
      expect(hrefs).toContain('/settings')
      expect(hrefs).toContain('/bots')
      expect(hrefs).toContain('/performance')
    })
  })

  describe('StrategyOverview', () => {
    it('renders guide.stratTitle', () => {
      renderPage()
      expect(screen.getByText('guide.stratTitle')).toBeInTheDocument()
    })

    it('renders all 6 strategy names', () => {
      renderPage()
      expect(screen.getByText('KI-Companion')).toBeInTheDocument()
      expect(screen.getByText('Sentiment Surfer')).toBeInTheDocument()
      expect(screen.getByText('Liquidation Hunter')).toBeInTheDocument()
      expect(screen.getAllByText(/^Degen$/).length).toBeGreaterThanOrEqual(1)
      expect(screen.getByText('Edge Indicator')).toBeInTheDocument()
      expect(screen.getByText('Claude-Edge')).toBeInTheDocument()
    })

    it('renders column headers', () => {
      renderPage()
      expect(screen.getByText('guide.stratColName')).toBeInTheDocument()
      expect(screen.getByText('guide.stratColDesc')).toBeInTheDocument()
      expect(screen.getByText('guide.stratColTf')).toBeInTheDocument()
    })
  })

  describe('Steps Timeline', () => {
    it('renders all 6 step titles', () => {
      renderPage()
      expect(screen.getByText('guide.step1Title')).toBeInTheDocument()
      expect(screen.getByText('guide.step2Title')).toBeInTheDocument()
      expect(screen.getByText('guide.step3Title')).toBeInTheDocument()
      expect(screen.getByText('guide.step4Title')).toBeInTheDocument()
      expect(screen.getByText('guide.step5Title')).toBeInTheDocument()
      expect(screen.getByText('guide.step6Title')).toBeInTheDocument()
    })

    it('renders all 6 step descriptions', () => {
      renderPage()
      expect(screen.getByText('guide.step1Desc')).toBeInTheDocument()
      expect(screen.getByText('guide.step2Desc')).toBeInTheDocument()
      expect(screen.getByText('guide.step3Desc')).toBeInTheDocument()
      expect(screen.getByText('guide.step4Desc')).toBeInTheDocument()
      expect(screen.getByText('guide.step5Desc')).toBeInTheDocument()
      expect(screen.getByText('guide.step6Desc')).toBeInTheDocument()
    })

    it('renders detail items for all steps', () => {
      renderPage()
      for (let step = 1; step <= 6; step++) {
        for (let detail = 1; detail <= 3; detail++) {
          expect(
            screen.getByText(`guide.step${step}Detail${detail}`),
          ).toBeInTheDocument()
        }
      }
    })
  })

  describe('Exchange Comparison', () => {
    it('renders guide.exchangeCompTitle', () => {
      renderPage()
      expect(screen.getByText('guide.exchangeCompTitle')).toBeInTheDocument()
    })

    it('renders exchange icons for bitget and hyperliquid', () => {
      renderPage()
      expect(screen.getAllByTestId('exchange-bitget').length).toBeGreaterThanOrEqual(1)
      expect(screen.getAllByTestId('exchange-hyperliquid').length).toBeGreaterThanOrEqual(1)
    })
  })

  describe('Exchange Setup Cards', () => {
    it('renders 3 setup cards', () => {
      renderPage()
      expect(screen.getByText('guide.bitgetSetupTitle')).toBeInTheDocument()
      expect(screen.getByText('guide.weexSetupTitle')).toBeInTheDocument()
      expect(screen.getByText('guide.hyperliquidSetupTitle')).toBeInTheDocument()
    })

    it('Bitget card is open by default and shows bitgetSetup1', () => {
      renderPage()
      expect(screen.getByText('guide.bitgetSetup1')).toBeInTheDocument()
    })

    it('toggles weex card open and closed', () => {
      renderPage()
      // weex card is closed by default
      expect(screen.queryByText('guide.weexSetup1')).not.toBeInTheDocument()

      // open the weex card
      fireEvent.click(screen.getByText('guide.weexSetupTitle'))
      expect(screen.getByText('guide.weexSetup1')).toBeInTheDocument()

      // close it again
      fireEvent.click(screen.getByText('guide.weexSetupTitle'))
      expect(screen.queryByText('guide.weexSetup1')).not.toBeInTheDocument()
    })
  })

  describe('Example Config', () => {
    it('renders guide.exampleTitle', () => {
      renderPage()
      expect(screen.getByText('guide.exampleTitle')).toBeInTheDocument()
    })
  })

  describe('Tip Box', () => {
    it('renders guide.tipTitle', () => {
      renderPage()
      expect(screen.getByText('guide.tipTitle')).toBeInTheDocument()
    })

    it('renders guide.tipText', () => {
      renderPage()
      expect(screen.getByText('guide.tipText')).toBeInTheDocument()
    })
  })
})
