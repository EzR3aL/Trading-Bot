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

// Mock api client (used by PrerequisiteBanner)
vi.mock('../api/client', () => {
  const mockApi = {
    get: vi.fn(() => Promise.resolve({ data: [] })),
    post: vi.fn(() => Promise.resolve({ data: {} })),
    put: vi.fn(() => Promise.resolve({ data: {} })),
    delete: vi.fn(() => Promise.resolve({ data: {} })),
  }
  return { __esModule: true, default: mockApi }
})

// Mock GuidedTour
vi.mock('../components/ui/GuidedTour', () => ({
  default: ({ tourId }: { tourId: string }) => (
    <div data-testid={`guided-tour-${tourId}`} />
  ),
  TourHelpButton: ({ tourId }: { tourId: string }) => (
    <button data-testid={`tour-help-${tourId}`} />
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
      // qsStep4 appears in both QuickStartFlow and WorkflowDiagram
      expect(screen.getAllByText('guide.qsStep4').length).toBeGreaterThanOrEqual(1)
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

  describe('How It Works', () => {
    it('renders guide.howItWorksTitle', () => {
      renderPage()
      expect(screen.getByText('guide.howItWorksTitle')).toBeInTheDocument()
    })

    it('renders all 3 card titles', () => {
      renderPage()
      expect(screen.getAllByText('guide.connectTitle').length).toBeGreaterThanOrEqual(1)
      expect(screen.getAllByText('guide.configureTitle').length).toBeGreaterThanOrEqual(1)
      expect(screen.getAllByText('guide.tradeTitle').length).toBeGreaterThanOrEqual(1)
    })

    it('renders card descriptions', () => {
      renderPage()
      expect(screen.getByText('guide.connectDesc')).toBeInTheDocument()
      expect(screen.getByText('guide.configureDesc')).toBeInTheDocument()
      expect(screen.getByText('guide.tradeDesc')).toBeInTheDocument()
    })

    it('renders bullet points for each card', () => {
      renderPage()
      expect(screen.getByText('guide.connectBullet1')).toBeInTheDocument()
      expect(screen.getByText('guide.configureBullet1')).toBeInTheDocument()
      expect(screen.getByText('guide.tradeBullet1')).toBeInTheDocument()
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

  describe('data-tour attributes', () => {
    it('has data-tour on all major sections', () => {
      const { container } = renderPage()
      expect(container.querySelector('[data-tour="guide-prereq"]')).toBeInTheDocument()
      expect(container.querySelector('[data-tour="guide-quickstart"]')).toBeInTheDocument()
      expect(container.querySelector('[data-tour="guide-how-it-works"]')).toBeInTheDocument()
      expect(container.querySelector('[data-tour="guide-strategies"]')).toBeInTheDocument()
      expect(container.querySelector('[data-tour="guide-exchanges"]')).toBeInTheDocument()
    })
  })

  describe('GuidedTour', () => {
    it('renders GuidedTour component', () => {
      renderPage()
      expect(screen.getByTestId('guided-tour-getting-started')).toBeInTheDocument()
    })

    it('renders TourHelpButton', () => {
      renderPage()
      expect(screen.getByTestId('tour-help-getting-started')).toBeInTheDocument()
    })
  })

  describe('Risk Gauge', () => {
    it('renders risk profile section', () => {
      renderPage()
      expect(screen.getByText('guide.riskTitle')).toBeInTheDocument()
      expect(screen.getByText('guide.riskConservative')).toBeInTheDocument()
      expect(screen.getByText('guide.riskModerate')).toBeInTheDocument()
      expect(screen.getByText('guide.riskAggressive')).toBeInTheDocument()
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
