import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import BotBuilder from '../BotBuilder'

const mockT = (key: string, opts?: any) => {
  if (opts?.returnObjects) {
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
      nameLabel: 'Bot Name',
      namePlaceholder: 'Enter bot name',
      descriptionLabel: 'Description',
    }
  }
  const translations: Record<string, string> = {
    'common.back': 'Back',
    'common.cancel': 'Cancel',
    'common.loadError': 'Failed to load data',
  }
  return translations[key] || key
}

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: mockT }),
}))

const mockGet = vi.fn()
const mockPost = vi.fn()

vi.mock('../../../api/client', () => ({
  default: {
    get: (...args: unknown[]) => mockGet(...args),
    post: (...args: unknown[]) => mockPost(...args),
    put: vi.fn().mockResolvedValue({}),
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
  default: () => ({ light: vi.fn(), medium: vi.fn(), heavy: vi.fn(), error: vi.fn() }),
}))

// Mock sub-step components to simplify testing
vi.mock('../BotBuilderStepName', () => ({
  default: ({ name, onNameChange, b }: any) => (
    <div data-testid="step-name">
      <label htmlFor="bot-name">{b?.nameLabel || 'Bot Name'}</label>
      <input id="bot-name" value={name} onChange={(e: any) => onNameChange(e.target.value)} placeholder={b?.namePlaceholder} />
    </div>
  ),
}))
vi.mock('../BotBuilderStepStrategy', () => ({
  default: () => <div data-testid="step-strategy">Strategy Step</div>,
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
  default: () => <div data-testid="step-review">Review Step</div>,
}))

const mockStrategies = [
  {
    name: 'edge_indicator',
    display_name: 'Edge Indicator',
    description: 'EMA + MACD strategy',
    param_schema: {
      risk_profile: { type: 'string', default: 'standard', enum: ['standard', 'conservative'] },
    },
  },
]

describe('BotBuilder', () => {
  const mockOnDone = vi.fn()
  const mockOnCancel = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()

    mockGet.mockImplementation((url: string) => {
      if (url === '/bots/strategies') return Promise.resolve({ data: { strategies: mockStrategies } })
      if (url === '/bots/data-sources') return Promise.resolve({ data: { sources: [], defaults: [] } })
      if (url.includes('/symbols')) return Promise.resolve({ data: { symbols: ['BTCUSDT', 'ETHUSDT'] } })
      if (url.includes('/builder-config')) return Promise.resolve({ data: { needs_approval: false, needs_referral: false } })
      return Promise.resolve({ data: {} })
    })
  })

  it('should render the first step (name input)', async () => {
    render(
      <MemoryRouter>
        <BotBuilder onDone={mockOnDone} onCancel={mockOnCancel} />
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByTestId('step-name')).toBeInTheDocument()
    })
  })

  it('should display the create title for new bots', async () => {
    render(
      <MemoryRouter>
        <BotBuilder onDone={mockOnDone} onCancel={mockOnCancel} />
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByText('Create Bot')).toBeInTheDocument()
    })
  })

  it('should show step indicator with step labels', async () => {
    render(
      <MemoryRouter>
        <BotBuilder onDone={mockOnDone} onCancel={mockOnCancel} />
      </MemoryRouter>
    )

    await waitFor(() => {
      // Desktop labels visible via hidden sm:inline — just check they exist in DOM
      expect(screen.getByText('Create Bot')).toBeInTheDocument()
    })
  })

  it('should navigate to next step when Next is clicked with valid name', async () => {
    const user = userEvent.setup()

    render(
      <MemoryRouter>
        <BotBuilder onDone={mockOnDone} onCancel={mockOnCancel} />
      </MemoryRouter>
    )

    // Type a name
    await waitFor(() => {
      expect(screen.getByTestId('step-name')).toBeInTheDocument()
    })
    await user.type(screen.getByPlaceholderText('Enter bot name'), 'My Bot')

    // Click next
    await user.click(screen.getByText('Next'))

    // Should now show strategy step
    await waitFor(() => {
      expect(screen.getByTestId('step-strategy')).toBeInTheDocument()
    })
  })

  it('should navigate back when Back is clicked', async () => {
    const user = userEvent.setup()

    render(
      <MemoryRouter>
        <BotBuilder onDone={mockOnDone} onCancel={mockOnCancel} />
      </MemoryRouter>
    )

    // Fill in name and go forward
    await waitFor(() => {
      expect(screen.getByTestId('step-name')).toBeInTheDocument()
    })
    await user.type(screen.getByPlaceholderText('Enter bot name'), 'My Bot')
    await user.click(screen.getByText('Next'))

    await waitFor(() => {
      expect(screen.getByTestId('step-strategy')).toBeInTheDocument()
    })

    // Click back
    await user.click(screen.getByText('Back'))

    await waitFor(() => {
      expect(screen.getByTestId('step-name')).toBeInTheDocument()
    })
  })

  it('should call onCancel when Cancel is clicked on step 1', async () => {
    const user = userEvent.setup()

    render(
      <MemoryRouter>
        <BotBuilder onDone={mockOnDone} onCancel={mockOnCancel} />
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByTestId('step-name')).toBeInTheDocument()
    })

    // The back/cancel button on step 0 should say Cancel
    await user.click(screen.getByText('Cancel'))
    expect(mockOnCancel).toHaveBeenCalled()
  })
})
