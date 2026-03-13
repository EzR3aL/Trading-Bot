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

/** Navigate to a section by clicking its tab button */
function navigateTo(sectionKey: string) {
  const navKey = `guide.nav${sectionKey.charAt(0).toUpperCase() + sectionKey.slice(1)}`
  // There may be both mobile and desktop nav buttons — click the first one
  const buttons = screen.getAllByText(navKey)
  fireEvent.click(buttons[0])
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

    it('renders prerequisite banner', () => {
      const { container } = renderPage()
      expect(container.querySelector('[data-tour="guide-prereq"]')).toBeInTheDocument()
    })
  })

  describe('QuickStartFlow (default section)', () => {
    it('renders guide.qsTitle', () => {
      renderPage()
      expect(screen.getByText('guide.qsTitle')).toBeInTheDocument()
    })

    it('renders guide.qsStep1 through qsStep4', () => {
      renderPage()
      expect(screen.getByText('guide.qsStep1')).toBeInTheDocument()
      expect(screen.getByText('guide.qsStep2')).toBeInTheDocument()
      expect(screen.getByText('guide.qsStep3')).toBeInTheDocument()
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

  describe('Tutorial section', () => {
    it('renders step titles after clicking tutorial tab', () => {
      renderPage()
      navigateTo('tutorial')
      expect(screen.getByText('guide.step1Title')).toBeInTheDocument()
      expect(screen.getByText('guide.step2Title')).toBeInTheDocument()
      expect(screen.getByText('guide.step3Title')).toBeInTheDocument()
    })

    it('renders all 6 step descriptions', () => {
      renderPage()
      navigateTo('tutorial')
      expect(screen.getByText('guide.step1Desc')).toBeInTheDocument()
      expect(screen.getByText('guide.step2Desc')).toBeInTheDocument()
      expect(screen.getByText('guide.step3Desc')).toBeInTheDocument()
      expect(screen.getByText('guide.step4Desc')).toBeInTheDocument()
      expect(screen.getByText('guide.step5Desc')).toBeInTheDocument()
      expect(screen.getByText('guide.step6Desc')).toBeInTheDocument()
    })

    it('first step is expanded by default', () => {
      renderPage()
      navigateTo('tutorial')
      // Step 1 detail should be visible (expanded by default)
      expect(screen.getByText('guide.step1Detail1')).toBeInTheDocument()
    })
  })

  describe('StrategyOverview section', () => {
    it('renders guide.stratTitle after clicking strategies tab', () => {
      renderPage()
      navigateTo('strategies')
      expect(screen.getByText('guide.stratTitle')).toBeInTheDocument()
    })

    it('renders strategy column headers', () => {
      renderPage()
      navigateTo('strategies')
      expect(screen.getByText('guide.stratColName')).toBeInTheDocument()
      expect(screen.getByText('guide.stratColDesc')).toBeInTheDocument()
      expect(screen.getByText('guide.stratColTf')).toBeInTheDocument()
    })
  })

  describe('Risk section', () => {
    it('renders risk profile section after clicking risk tab', () => {
      renderPage()
      navigateTo('risk')
      expect(screen.getByText('guide.riskTitle')).toBeInTheDocument()
      expect(screen.getByText('guide.riskConservative')).toBeInTheDocument()
      expect(screen.getByText('guide.riskModerate')).toBeInTheDocument()
      expect(screen.getByText('guide.riskAggressive')).toBeInTheDocument()
    })
  })

  describe('Exchanges section', () => {
    it('renders exchange comparison after clicking exchanges tab', () => {
      renderPage()
      navigateTo('exchanges')
      expect(screen.getByText('guide.exchangeCompTitle')).toBeInTheDocument()
    })

    it('renders exchange icons', () => {
      renderPage()
      navigateTo('exchanges')
      expect(screen.getAllByTestId('exchange-bitget').length).toBeGreaterThanOrEqual(1)
      expect(screen.getAllByTestId('exchange-hyperliquid').length).toBeGreaterThanOrEqual(1)
    })

    it('renders setup cards', () => {
      renderPage()
      navigateTo('exchanges')
      expect(screen.getByText('guide.bitgetSetupTitle')).toBeInTheDocument()
      expect(screen.getByText('guide.weexSetupTitle')).toBeInTheDocument()
      expect(screen.getByText('guide.hyperliquidSetupTitle')).toBeInTheDocument()
    })

    it('Bitget card is open by default and shows bitgetSetup1', () => {
      renderPage()
      navigateTo('exchanges')
      expect(screen.getByText('guide.bitgetSetup1')).toBeInTheDocument()
    })

    it('toggles weex card open and closed', () => {
      renderPage()
      navigateTo('exchanges')

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

  describe('Navigation', () => {
    it('renders all 6 section tabs', () => {
      renderPage()
      expect(screen.getAllByText('guide.navQuickstart').length).toBeGreaterThanOrEqual(1)
      expect(screen.getAllByText('guide.navTutorial').length).toBeGreaterThanOrEqual(1)
      expect(screen.getAllByText('guide.navStrategies').length).toBeGreaterThanOrEqual(1)
      expect(screen.getAllByText('guide.navRisk').length).toBeGreaterThanOrEqual(1)
      expect(screen.getAllByText('guide.navExchanges').length).toBeGreaterThanOrEqual(1)
      expect(screen.getAllByText('guide.navSecurity').length).toBeGreaterThanOrEqual(1)
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
})
