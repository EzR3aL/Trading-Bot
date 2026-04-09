import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import BotBuilderStepStrategy from '../BotBuilderStepStrategy'
import type { Strategy } from '../BotBuilderTypes'

// Mock i18n
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: any) => {
      const translations: Record<string, string> = {
        'bots.builder.deterministic': 'Deterministic',
        'bots.builder.creative': 'Creative',
        'bots.builder.customPromptPlaceholder': 'Enter custom prompt...',
        'bots.builder.paramLabel_risk_profile': 'Risk Profile',
        'bots.builder.paramDesc_risk_profile': 'Choose risk profile',
        'bots.builder.paramOption_risk_profile_standard': 'Standard',
        'bots.builder.paramOption_risk_profile_conservative': 'Conservative',
      }
      // Handle defaultValue fallback
      if (opts?.defaultValue && !translations[key]) return opts.defaultValue
      return translations[key] || key
    },
  }),
  Trans: ({ i18nKey, values }: any) => <span>{i18nKey} {JSON.stringify(values)}</span>,
}))

// Mock API client
vi.mock('../../../api/client', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  },
  setTokenExpiry: vi.fn(),
  clearTokenExpiry: vi.fn(),
}))

// Mock UI components
vi.mock('../../ui/FilterDropdown', () => ({
  default: ({ value, onChange, options, ariaLabel }: any) => (
    <select aria-label={ariaLabel} value={value} onChange={(e: any) => onChange(e.target.value)}>
      {options?.map((opt: any) => (
        <option key={opt.value} value={opt.value}>{opt.label}</option>
      ))}
    </select>
  ),
}))

vi.mock('../../ui/NumInput', () => ({
  default: (props: any) => <input type="number" {...props} />,
}))

// Mock strategy label utility
vi.mock('../../../constants/strategies', () => ({
  strategyLabel: (name: string) => {
    const map: Record<string, string> = {
      edge_indicator: 'Edge Indicator',
      liquidation_hunter: 'Liquidation Hunter',
    }
    return map[name] || name
  },
}))

const mockStrategies: Strategy[] = [
  {
    name: 'edge_indicator',
    description: 'EMA + MACD strategy',
    param_schema: {
      risk_profile: {
        type: 'select',
        label: 'Risk Profile',
        description: 'Choose risk profile',
        default: 'standard',
        options: [
          { value: 'standard', label: 'Standard' },
          { value: 'conservative', label: 'Conservative' },
        ],
      },
    },
  },
  {
    name: 'liquidation_hunter',
    description: 'Liquidation cascade strategy',
    param_schema: {},
  },
]

const defaultB: Record<string, string> = {
  selectStrategy: 'Select Strategy',
  viewGrid: 'Grid View',
  viewList: 'List View',
  proModeParamsHint: 'Enable Pro Mode for advanced settings',
  proModeParamsActiveHint: 'Advanced parameters are visible',
}

const defaultProps = {
  strategies: mockStrategies,
  strategyType: '',
  strategyParams: {},
  strategyView: 'grid' as const,
  proMode: false,
  onStrategyChange: vi.fn(),
  onStrategyParamsChange: vi.fn(),
  onStrategyViewChange: vi.fn(),
  onToggleProMode: vi.fn(),
  b: defaultB,
}

describe('BotBuilderStepStrategy', () => {
  it('renders strategy options in grid view', () => {
    render(<BotBuilderStepStrategy {...defaultProps} />)

    expect(screen.getByText('Edge Indicator')).toBeInTheDocument()
    expect(screen.getByText('Liquidation Hunter')).toBeInTheDocument()
  })

  it('renders strategy options in list view', () => {
    render(<BotBuilderStepStrategy {...defaultProps} strategyView="list" />)

    expect(screen.getByText('Edge Indicator')).toBeInTheDocument()
    expect(screen.getByText('Liquidation Hunter')).toBeInTheDocument()
  })

  it('calls onStrategyChange when a strategy is clicked', async () => {
    const onStrategyChange = vi.fn()
    const user = userEvent.setup()

    render(<BotBuilderStepStrategy {...defaultProps} onStrategyChange={onStrategyChange} />)

    await user.click(screen.getByText('Edge Indicator'))
    expect(onStrategyChange).toHaveBeenCalledWith('edge_indicator')
  })

  it('shows strategy description', () => {
    render(<BotBuilderStepStrategy {...defaultProps} />)

    expect(screen.getByText('EMA + MACD strategy')).toBeInTheDocument()
    expect(screen.getByText('Liquidation cascade strategy')).toBeInTheDocument()
  })

  it('shows strategy parameters when strategy with params is selected', () => {
    render(
      <BotBuilderStepStrategy
        {...defaultProps}
        strategyType="edge_indicator"
        strategyParams={{ risk_profile: 'standard' }}
      />
    )

    // The select dropdown for risk_profile should be rendered
    expect(screen.getByRole('combobox', { name: /risk profile/i })).toBeInTheDocument()
  })

  it('calls onStrategyParamsChange when a parameter is changed', async () => {
    const onStrategyParamsChange = vi.fn()
    const user = userEvent.setup()

    render(
      <BotBuilderStepStrategy
        {...defaultProps}
        strategyType="edge_indicator"
        strategyParams={{ risk_profile: 'standard' }}
        onStrategyParamsChange={onStrategyParamsChange}
      />
    )

    await user.selectOptions(screen.getByRole('combobox', { name: /risk profile/i }), 'conservative')
    // setParams merges the update, so it includes kline_interval for risk_profile
    expect(onStrategyParamsChange).toHaveBeenCalledWith(
      expect.objectContaining({ risk_profile: 'conservative' })
    )
  })

  it('toggles between grid and list view', async () => {
    const onStrategyViewChange = vi.fn()
    const user = userEvent.setup()

    render(
      <BotBuilderStepStrategy {...defaultProps} onStrategyViewChange={onStrategyViewChange} />
    )

    await user.click(screen.getByTitle('List View'))
    expect(onStrategyViewChange).toHaveBeenCalledWith('list')
  })

  it('renders Pro Mode toggle when strategy has numeric params', () => {
    const strategyWithNumeric: Strategy[] = [
      {
        name: 'test_strat',
        description: 'Test strategy',
        param_schema: {
          some_number: {
            type: 'int',
            label: 'Some Number',
            description: 'A number param',
            default: 10,
            min: 1,
            max: 100,
          },
        },
      },
    ]

    render(
      <BotBuilderStepStrategy
        {...defaultProps}
        strategies={strategyWithNumeric}
        strategyType="test_strat"
        strategyParams={{ some_number: 10 }}
      />
    )

    expect(screen.getByText('Pro Mode')).toBeInTheDocument()
  })

  it('calls onToggleProMode when Pro Mode switch is clicked', async () => {
    const onToggleProMode = vi.fn()
    const user = userEvent.setup()

    const strategyWithNumeric: Strategy[] = [
      {
        name: 'test_strat',
        description: 'Test',
        param_schema: {
          some_number: {
            type: 'int',
            label: 'Number',
            description: 'desc',
            default: 10,
            min: 1,
            max: 100,
          },
        },
      },
    ]

    render(
      <BotBuilderStepStrategy
        {...defaultProps}
        strategies={strategyWithNumeric}
        strategyType="test_strat"
        strategyParams={{ some_number: 10 }}
        onToggleProMode={onToggleProMode}
      />
    )

    await user.click(screen.getByRole('switch', { name: 'Pro Mode' }))
    expect(onToggleProMode).toHaveBeenCalled()
  })

  it('does not show params section for strategy without params', () => {
    render(
      <BotBuilderStepStrategy
        {...defaultProps}
        strategyType="liquidation_hunter"
        strategyParams={{}}
      />
    )

    // No Pro Mode or param selects should appear
    expect(screen.queryByText('Pro Mode')).not.toBeInTheDocument()
  })
})
