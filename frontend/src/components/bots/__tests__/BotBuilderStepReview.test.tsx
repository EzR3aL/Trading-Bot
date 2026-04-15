import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import BotBuilderStepReview from '../BotBuilderStepReview'

// Mock i18n
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: any) => {
      const translations: Record<string, string> = {
        'bots.builder.marginMode': 'Margin Mode',
        'bots.builder.cross': 'Cross',
        'bots.builder.isolated': 'Isolated',
        'bots.builder.interval': 'Interval',
        'bots.builder.perAssetConfig': 'Per-Asset Config',
        'bots.builder.noTpSlLabel': 'No TP/SL',
        'bots.builder.symbolConflictTitle': 'Symbol Conflict',
        'bots.builder.symbolConflictHint': 'Resolve conflicts before creating',
        'bots.builder.riskLimits': 'Risk Limits',
      }
      if (opts?.symbol) return `${opts.symbol} already used by ${opts.botName}`
      return translations[key] || key
    },
  }),
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

// Mock ExchangeLogo
vi.mock('../../ui/ExchangeLogo', () => ({
  default: ({ exchange }: { exchange: string }) => <span data-testid={`logo-${exchange}`}>{exchange}</span>,
}))

// Mock strategy label
vi.mock('../../../constants/strategies', () => ({
  strategyLabel: (name: string) => {
    const map: Record<string, string> = {
      edge_indicator: 'Edge Indicator',
      liquidation_hunter: 'Liquidation Hunter',
    }
    return map[name] || name
  },
}))

const defaultB: Record<string, string> = {
  review: 'Review',
  name: 'Name',
  mode: 'Mode',
  strategy: 'Strategy',
  exchange: 'Exchange',
  tradingPairs: 'Trading Pairs',
  schedule: 'Schedule',
  maxTrades: 'Max Trades',
  dailyLossLimit: 'Daily Loss Limit',
  riskLimits: 'Risk Limits',
  riskDisclaimerTitle: 'Risk Disclaimer',
  riskDisclaimer: 'Trading involves risk. You could lose your funds.',
  riskAccept: 'I understand and accept the risks',
  dataSources: 'Data Sources',
  fixedSources: 'fixed',
  sourcesSelected: 'selected',
}

const defaultProps = {
  name: 'My Test Bot',
  strategyType: 'edge_indicator',
  strategyParams: { risk_profile: 'standard' },
  exchangeType: 'bitget',
  mode: 'demo',
  marginMode: 'cross' as const,
  tradingPairs: ['BTCUSDT', 'ETHUSDT'],
  perAssetConfig: {
    BTCUSDT: { position_usdt: 500, leverage: 5, tp: 3, sl: 2 },
    ETHUSDT: { position_usdt: 300, leverage: 3 },
  },
  balancePreview: null,
  scheduleType: 'interval',
  intervalMinutes: 60 as number | '',
  customHours: [] as number[],
  maxTrades: null,
  dailyLossLimit: null,
  symbolConflicts: [],
  selectedSources: [],
  usesData: false,
  hasFixedSources: false,
  riskAccepted: false,
  onRiskAcceptedChange: vi.fn(),
  discordConfigured: false,
  telegramConfigured: false,
  discordWebhookUrl: '',
  telegramBotToken: '',
  pnlAlertSettings: { enabled: false, thresholds: [], direction: 'both' as const },
  b: defaultB,
}

describe('BotBuilderStepReview', () => {
  it('renders the review heading', () => {
    render(<BotBuilderStepReview {...defaultProps} />)

    expect(screen.getByText('Review')).toBeInTheDocument()
  })

  it('shows bot name', () => {
    render(<BotBuilderStepReview {...defaultProps} />)

    expect(screen.getByText('My Test Bot')).toBeInTheDocument()
  })

  it('shows bot mode', () => {
    render(<BotBuilderStepReview {...defaultProps} />)

    expect(screen.getByText('DEMO')).toBeInTheDocument()
  })

  it('shows strategy name', () => {
    render(<BotBuilderStepReview {...defaultProps} />)

    expect(screen.getByText('Edge Indicator')).toBeInTheDocument()
  })

  it('shows exchange logo', () => {
    render(<BotBuilderStepReview {...defaultProps} />)

    expect(screen.getByTestId('logo-bitget')).toBeInTheDocument()
  })

  it('shows trading pairs', () => {
    render(<BotBuilderStepReview {...defaultProps} />)

    // Pairs appear in both the trading pairs section and per-asset config
    expect(screen.getAllByText('BTCUSDT').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('ETHUSDT').length).toBeGreaterThanOrEqual(1)
  })

  it('shows schedule info', () => {
    render(<BotBuilderStepReview {...defaultProps} />)

    expect(screen.getByText('Interval (60 Min.)')).toBeInTheDocument()
  })

  it('shows risk disclaimer with checkbox', () => {
    render(<BotBuilderStepReview {...defaultProps} />)

    expect(screen.getByText('Risk Disclaimer')).toBeInTheDocument()
    expect(screen.getByText('Trading involves risk. You could lose your funds.')).toBeInTheDocument()
    expect(screen.getByRole('checkbox')).toBeInTheDocument()
  })

  it('calls onRiskAcceptedChange when checkbox is toggled', async () => {
    const onRiskAcceptedChange = vi.fn()
    const user = userEvent.setup()

    render(<BotBuilderStepReview {...defaultProps} onRiskAcceptedChange={onRiskAcceptedChange} />)

    await user.click(screen.getByRole('checkbox'))
    expect(onRiskAcceptedChange).toHaveBeenCalledWith(true)
  })

  it('shows risk limits when maxTrades is set', () => {
    render(<BotBuilderStepReview {...defaultProps} maxTrades={10} />)

    expect(screen.getByText('Risk Limits')).toBeInTheDocument()
    expect(screen.getByText('10')).toBeInTheDocument()
  })

  it('shows risk limits when dailyLossLimit is set', () => {
    render(<BotBuilderStepReview {...defaultProps} dailyLossLimit={5} />)

    expect(screen.getByText('5%')).toBeInTheDocument()
  })

  it('shows symbol conflict warning when conflicts exist', () => {
    render(
      <BotBuilderStepReview
        {...defaultProps}
        symbolConflicts={[{
          symbol: 'BTCUSDT',
          existing_bot_id: 1,
          existing_bot_name: 'Other Bot',
          existing_bot_mode: 'demo',
        }]}
      />
    )

    expect(screen.getByText('Symbol Conflict')).toBeInTheDocument()
  })

  it('shows data sources section when usesData is true', () => {
    render(
      <BotBuilderStepReview
        {...defaultProps}
        usesData={true}
        selectedSources={['fear_greed', 'funding_rate']}
        hasFixedSources={true}
      />
    )

    // Data Sources appears both as section header and ReviewRow label
    expect(screen.getAllByText('Data Sources').length).toBeGreaterThanOrEqual(1)
  })

  it('shows margin mode', () => {
    render(<BotBuilderStepReview {...defaultProps} />)

    expect(screen.getByText('Margin Mode')).toBeInTheDocument()
  })

  it('shows live mode in green', () => {
    render(<BotBuilderStepReview {...defaultProps} mode="live" />)

    const liveText = screen.getByText('LIVE')
    expect(liveText).toHaveClass('text-emerald-400')
  })

  it('shows per-asset config for trading pairs', () => {
    render(<BotBuilderStepReview {...defaultProps} />)

    // Per-asset config section should show trading pair details
    expect(screen.getByText('Per-Asset Config')).toBeInTheDocument()
  })

  it('hides trading pairs section for copy_trading strategy', () => {
    render(
      <BotBuilderStepReview
        {...defaultProps}
        strategyType="copy_trading"
        strategyParams={{ source_wallet: '0xabc123def456', budget_usdt: 1000, max_slots: 5 }}
        tradingPairs={[]}
      />
    )

    // Should show Copy Trading section instead
    expect(screen.getByText('Copy Trading')).toBeInTheDocument()
  })
})
