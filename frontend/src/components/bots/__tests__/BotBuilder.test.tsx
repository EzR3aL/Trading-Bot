import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import BotBuilder from '../BotBuilder'

const mockT = (key: string, opts?: unknown) => {
  if (opts && typeof opts === 'object' && 'returnObjects' in (opts as Record<string, unknown>)) {
    return {
      title: 'Create Bot',
      editTitle: 'Edit Bot',
      step1: 'Name',
      step2: 'Strategy',
      step2b: 'Data Sources',
      step3: 'Exchange',
      step4: 'Notifications',
      step5: 'Schedule',
      step6: 'Review',
      next: 'Next',
      back: 'Back',
      save: 'Save',
      create: 'Create',
      createAndStart: 'Create & Start',
      nameLabel: 'Bot Name',
      namePlaceholder: 'Enter bot name',
      descriptionLabel: 'Description',
    }
  }
  const translations: Record<string, string> = {
    'common.back': 'Back',
    'common.cancel': 'Cancel',
    'common.loadError': 'Failed to load data',
    'bots.builder.riskReAckReason':
      'Du hast das Risikoprofil erhöht. Bitte bestätige den Risikohinweis erneut.',
    'bots.builder.startShort': 'Start',
    'bots.builder.discordTestMissingUrl': 'Please enter Discord webhook URL',
    'bots.builder.discordTestSent': 'Discord test message sent!',
    'bots.builder.discordTestFailed': 'Discord test failed',
    'bots.builder.telegramTestMissingCredentials': 'Please enter Telegram bot token and chat ID',
    'bots.builder.telegramTestSent': 'Telegram test message sent!',
    'bots.builder.telegramTestFailed': 'Telegram test failed',
  }
  return translations[key] || key
}

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: mockT }),
}))

const mockGet = vi.fn()
const mockPost = vi.fn()
const mockPut = vi.fn().mockResolvedValue({})

vi.mock('../../../api/client', () => ({
  default: {
    get: (...args: unknown[]) => mockGet(...args),
    post: (...args: unknown[]) => mockPost(...args),
    put: (...args: unknown[]) => mockPut(...args),
    interceptors: {
      request: { use: vi.fn() },
      response: { use: vi.fn() },
    },
  },
  setTokenExpiry: vi.fn(),
  clearTokenExpiry: vi.fn(),
}))

vi.mock('../../../utils/api-error', () => ({
  getApiErrorMessage: vi.fn(() => 'error'),
}))

vi.mock('../../../hooks/useHaptic', () => ({
  default: () => ({ light: vi.fn(), medium: vi.fn(), heavy: vi.fn(), error: vi.fn(), success: vi.fn() }),
}))

// Mock sub-step components to simplify testing. The Review step is the one we
// care about for risk-ack behaviour — it exposes the checkbox directly.
vi.mock('../BotBuilderStepName', () => ({
  default: ({ name, onNameChange, b }: { name: string; onNameChange: (v: string) => void; b?: { nameLabel?: string; namePlaceholder?: string } }) => (
    <div data-testid="step-name">
      <label htmlFor="bot-name">{b?.nameLabel || 'Bot Name'}</label>
      <input id="bot-name" value={name} onChange={(e) => onNameChange(e.target.value)} placeholder={b?.namePlaceholder} />
    </div>
  ),
}))
vi.mock('../BotBuilderStepStrategy', () => ({
  default: ({ strategyParams, onStrategyParamsChange }: {
    strategyParams: Record<string, unknown>
    onStrategyParamsChange: (p: Record<string, unknown>) => void
  }) => (
    <div data-testid="step-strategy">
      <span data-testid="current-risk">{String(strategyParams.risk_profile ?? '')}</span>
      <button
        type="button"
        data-testid="set-risk-conservative"
        onClick={() => onStrategyParamsChange({ ...strategyParams, risk_profile: 'conservative' })}
      >set-conservative</button>
      <button
        type="button"
        data-testid="set-risk-standard"
        onClick={() => onStrategyParamsChange({ ...strategyParams, risk_profile: 'standard' })}
      >set-standard</button>
      <button
        type="button"
        data-testid="set-risk-aggressive"
        onClick={() => onStrategyParamsChange({ ...strategyParams, risk_profile: 'aggressive' })}
      >set-aggressive</button>
    </div>
  ),
}))
vi.mock('../BotBuilderStepDataSources', () => ({
  default: () => <div data-testid="step-datasources">Data Sources Step</div>,
}))
vi.mock('../BotBuilderStepExchange', () => ({
  default: () => <div data-testid="step-exchange">Exchange Step</div>,
}))
vi.mock('../BotBuilderStepNotifications', () => ({
  default: () => <div data-testid="step-notifications">Notifications Step</div>,
}))
vi.mock('../BotBuilderStepSchedule', () => ({
  default: () => <div data-testid="step-schedule">Schedule Step</div>,
}))
vi.mock('../BotBuilderStepReview', () => ({
  default: ({ riskAccepted, onRiskAcceptedChange }: {
    riskAccepted: boolean
    onRiskAcceptedChange: (v: boolean) => void
  }) => (
    <div data-testid="step-review">
      <label>
        <input
          type="checkbox"
          data-testid="risk-accept-checkbox"
          checked={riskAccepted}
          onChange={(e) => onRiskAcceptedChange(e.target.checked)}
        />
        Accept risk
      </label>
    </div>
  ),
}))

const mockStrategies = [
  {
    name: 'edge_indicator',
    display_name: 'Edge Indicator',
    description: 'EMA + MACD strategy',
    param_schema: {
      risk_profile: { type: 'string', default: 'standard', enum: ['standard', 'conservative', 'aggressive'] },
    },
  },
]

type BalanceOverview = { exchange_type: string; mode: string }[]

const defaultGetImpl = (overviewPayload: BalanceOverview = [{ exchange_type: 'bitget', mode: 'demo' }]) =>
  (url: string) => {
    if (url === '/bots/strategies') return Promise.resolve({ data: { strategies: mockStrategies } })
    if (url === '/bots/data-sources') return Promise.resolve({ data: { sources: [], defaults: [] } })
    if (url.includes('/symbols')) return Promise.resolve({ data: { symbols: ['BTCUSDT', 'ETHUSDT'] } })
    if (url.includes('/builder-config')) return Promise.resolve({ data: { needs_approval: false, needs_referral: false } })
    if (url.includes('/balance-overview')) return Promise.resolve({ data: { exchanges: overviewPayload } })
    if (url.includes('/balance-preview')) return Promise.resolve({ data: null })
    if (url.includes('/symbol-conflicts')) return Promise.resolve({ data: { conflicts: [] } })
    return Promise.resolve({ data: {} })
  }

/** Click through all the Next buttons to land on the Review step. */
async function advanceToReview(user: ReturnType<typeof userEvent.setup>) {
  await waitFor(() => expect(screen.getByTestId('step-name')).toBeInTheDocument())
  await user.type(screen.getByPlaceholderText('Enter bot name'), 'My Bot')
  // Click Next until we reach the Review step.
  let guard = 0
  while (!screen.queryByTestId('step-review') && guard < 10) {
    const nextBtn = screen.queryByText('Next')
    if (!nextBtn) break
    await user.click(nextBtn)
    guard += 1
  }
  await waitFor(() => expect(screen.getByTestId('step-review')).toBeInTheDocument())
}

describe('BotBuilder', () => {
  const mockOnDone = vi.fn()
  const mockOnCancel = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
    mockGet.mockImplementation(defaultGetImpl())
  })

  it('renders the first step (name input)', async () => {
    render(
      <MemoryRouter>
        <BotBuilder onDone={mockOnDone} onCancel={mockOnCancel} />
      </MemoryRouter>
    )
    await waitFor(() => expect(screen.getByTestId('step-name')).toBeInTheDocument())
  })

  it('displays the create title for new bots', async () => {
    render(
      <MemoryRouter>
        <BotBuilder onDone={mockOnDone} onCancel={mockOnCancel} />
      </MemoryRouter>
    )
    await waitFor(() => expect(screen.getByText('Create Bot')).toBeInTheDocument())
  })

  it('navigates to next step when Next is clicked with valid name', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <BotBuilder onDone={mockOnDone} onCancel={mockOnCancel} />
      </MemoryRouter>
    )
    await waitFor(() => expect(screen.getByTestId('step-name')).toBeInTheDocument())
    await user.type(screen.getByPlaceholderText('Enter bot name'), 'My Bot')
    await user.click(screen.getByText('Next'))
    await waitFor(() => expect(screen.getByTestId('step-strategy')).toBeInTheDocument())
  })

  it('navigates back when Back is clicked', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <BotBuilder onDone={mockOnDone} onCancel={mockOnCancel} />
      </MemoryRouter>
    )
    await waitFor(() => expect(screen.getByTestId('step-name')).toBeInTheDocument())
    await user.type(screen.getByPlaceholderText('Enter bot name'), 'My Bot')
    await user.click(screen.getByText('Next'))
    await waitFor(() => expect(screen.getByTestId('step-strategy')).toBeInTheDocument())
    await user.click(screen.getByText('Back'))
    await waitFor(() => expect(screen.getByTestId('step-name')).toBeInTheDocument())
  })

  it('calls onCancel when Cancel is clicked on step 1', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <BotBuilder onDone={mockOnDone} onCancel={mockOnCancel} />
      </MemoryRouter>
    )
    await waitFor(() => expect(screen.getByTestId('step-name')).toBeInTheDocument())
    await user.click(screen.getByText('Cancel'))
    expect(mockOnCancel).toHaveBeenCalled()
  })

  describe('risk acknowledgment (create mode)', () => {
    it('disables Create until the risk checkbox is checked and enables it after', async () => {
      const user = userEvent.setup()
      render(
        <MemoryRouter>
          <BotBuilder onDone={mockOnDone} onCancel={mockOnCancel} />
        </MemoryRouter>
      )
      await advanceToReview(user)

      const createBtn = screen.getByRole('button', { name: /Create$/ })
      expect(createBtn).toBeDisabled()

      await user.click(screen.getByTestId('risk-accept-checkbox'))
      expect(createBtn).not.toBeDisabled()
    })
  })

  describe('risk re-acknowledgment (edit mode)', () => {
    const existingBot = (riskProfile: string) => ({
      data: {
        name: 'Existing Bot',
        description: '',
        strategy_type: 'edge_indicator',
        strategy_params: { risk_profile: riskProfile },
        exchange_type: 'bitget',
        mode: 'demo',
        margin_mode: 'cross',
        trading_pairs: ['BTCUSDT'],
        max_trades_per_day: null,
        daily_loss_limit_percent: null,
        schedule_type: 'interval',
        schedule_config: { interval_minutes: 60 },
        discord_webhook_configured: false,
        telegram_configured: false,
      },
    })

    const setupEditMode = (riskProfile: string) => {
      mockGet.mockImplementation((url: string) => {
        if (url === `/bots/42`) return Promise.resolve(existingBot(riskProfile))
        return defaultGetImpl()(url)
      })
    }

    it('does NOT require re-ack when risk is kept the same', async () => {
      const user = userEvent.setup()
      setupEditMode('standard')
      render(
        <MemoryRouter>
          <BotBuilder botId={42} onDone={mockOnDone} onCancel={mockOnCancel} />
        </MemoryRouter>
      )
      await advanceToReview(user)

      // Risk stays at 'standard' — Save should be enabled without checking the checkbox.
      const saveBtn = screen.getByRole('button', { name: /Save/ })
      expect(saveBtn).not.toBeDisabled()
      expect(screen.queryByText(/Risikoprofil erhöht/i)).not.toBeInTheDocument()
    })

    it('does NOT require re-ack when risk is LOWERED', async () => {
      const user = userEvent.setup()
      setupEditMode('aggressive')
      render(
        <MemoryRouter>
          <BotBuilder botId={42} onDone={mockOnDone} onCancel={mockOnCancel} />
        </MemoryRouter>
      )
      // Wait for the bot to load with aggressive risk.
      await waitFor(() => expect(mockGet).toHaveBeenCalledWith('/bots/42'))

      // Navigate to strategy step and lower risk to standard.
      await waitFor(() => expect(screen.getByTestId('step-name')).toBeInTheDocument())
      await user.click(screen.getByText('Next'))
      await waitFor(() => expect(screen.getByTestId('step-strategy')).toBeInTheDocument())
      await user.click(screen.getByTestId('set-risk-standard'))

      // Advance to the Review step.
      let guard = 0
      while (!screen.queryByTestId('step-review') && guard < 10) {
        await user.click(screen.getByText('Next'))
        guard += 1
      }
      await waitFor(() => expect(screen.getByTestId('step-review')).toBeInTheDocument())

      const saveBtn = screen.getByRole('button', { name: /Save/ })
      expect(saveBtn).not.toBeDisabled()
      expect(screen.queryByText(/Risikoprofil erhöht/i)).not.toBeInTheDocument()
    })

    it('REQUIRES re-ack when risk is RAISED — Save disabled until the checkbox is checked', async () => {
      const user = userEvent.setup()
      setupEditMode('conservative')
      render(
        <MemoryRouter>
          <BotBuilder botId={42} onDone={mockOnDone} onCancel={mockOnCancel} />
        </MemoryRouter>
      )
      await waitFor(() => expect(mockGet).toHaveBeenCalledWith('/bots/42'))

      await waitFor(() => expect(screen.getByTestId('step-name')).toBeInTheDocument())
      await user.click(screen.getByText('Next'))
      await waitFor(() => expect(screen.getByTestId('step-strategy')).toBeInTheDocument())

      // Raise risk from conservative to aggressive.
      await user.click(screen.getByTestId('set-risk-aggressive'))

      // Advance to Review.
      let guard = 0
      while (!screen.queryByTestId('step-review') && guard < 10) {
        await user.click(screen.getByText('Next'))
        guard += 1
      }
      await waitFor(() => expect(screen.getByTestId('step-review')).toBeInTheDocument())

      // Banner should explain the re-ack.
      expect(screen.getByText(/Risikoprofil erhöht/i)).toBeInTheDocument()

      const saveBtn = screen.getByRole('button', { name: /Save/ })
      expect(saveBtn).toBeDisabled()

      // Checking the risk-accept box should unlock Save.
      await user.click(screen.getByTestId('risk-accept-checkbox'))
      expect(saveBtn).not.toBeDisabled()
    })
  })
})
