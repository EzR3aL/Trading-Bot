import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import BotBuilderStepExchange from '../BotBuilderStepExchange'
import type { BalancePreview } from '../BotBuilderTypes'

// Mock i18n
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: any) => {
      const translations: Record<string, string> = {
        'bots.builder.marginMode': 'Margin Mode',
        'bots.builder.cross': 'Cross',
        'bots.builder.isolated': 'Isolated',
        'bots.builder.searchSymbols': 'Search symbols...',
        'bots.builder.available': 'available',
        'bots.builder.maxPairs': 'Max 10 pairs',
        'bots.builder.perAssetConfig': 'Per-Asset Config',
        'bots.builder.perAssetHint': 'Configure each pair',
        'bots.builder.budgetUsdt': 'Budget (USDT)',
        'bots.builder.leverageHint': 'Leverage hint',
        'bots.builder.tpHint': 'Take profit hint',
        'bots.builder.slHint': 'Stop loss hint',
        'bots.builder.marginModeHintCross': 'Cross: shared margin',
        'bots.builder.marginModeHintIsolated': 'Isolated: separate margin',
        'bots.builder.demoNotSupported': 'Demo not supported',
        'bots.builder.demoNotSupportedHint': 'Demo not available for this exchange',
        'bots.builder.noTpSlWarning': 'No TP/SL set',
        'bots.builder.noSlWarning': 'No SL set',
        'bots.builder.noConnectionsTitle': 'No connections',
        'bots.builder.noConnectionsHint': 'Connect an exchange first',
        'bots.builder.allExchanges': 'All Exchanges',
        'bots.builder.exchange': 'Exchange',
        'bots.builder.equity': 'Equity',
        'bots.builder.allocated': 'Allocated',
        'bots.builder.mode': 'Mode',
      }
      return translations[key] || (typeof fallback === 'string' ? fallback : key)
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

// Mock sub-components to simplify
vi.mock('../../ui/ExchangeLogo', () => ({
  default: ({ exchange }: { exchange: string }) => <span data-testid={`logo-${exchange}`}>{exchange}</span>,
}))

vi.mock('../../ui/NumInput', () => ({
  default: (props: any) => <input type="number" {...props} />,
}))

vi.mock('../CopyTradingStepExchange', () => ({
  default: () => <div data-testid="copy-trading-exchange">Copy Trading Exchange</div>,
}))

const defaultB: Record<string, string> = {
  exchange: 'Exchange',
  mode: 'Mode',
  demo: 'Demo',
  live: 'Live',
  tradingPairs: 'Trading Pairs',
  leverage: 'Leverage',
  maxTrades: 'Max Trades',
  dailyLossLimit: 'Daily Loss Limit',
}

const defaultProps = {
  exchangeType: 'bitget',
  mode: 'demo',
  marginMode: 'cross' as const,
  tradingPairs: [] as string[],
  perAssetConfig: {},
  exchangeSymbols: ['BTCUSDT', 'ETHUSDT', 'SOLUSDT'],
  symbolsLoading: false,
  balancePreview: null,
  balanceOverview: [] as BalancePreview[],
  overviewLoading: false,
  symbolConflicts: [],
  onExchangeTypeChange: vi.fn(),
  onModeChange: vi.fn(),
  onMarginModeChange: vi.fn(),
  onTogglePair: vi.fn(),
  onPerAssetConfigChange: vi.fn(),
  b: defaultB,
}

describe('BotBuilderStepExchange', () => {
  it('renders exchange selection buttons', () => {
    render(
      <MemoryRouter>
        <BotBuilderStepExchange {...defaultProps} />
      </MemoryRouter>
    )

    // Should render logos for all exchanges
    expect(screen.getByTestId('logo-bitget')).toBeInTheDocument()
    expect(screen.getByTestId('logo-weex')).toBeInTheDocument()
    expect(screen.getByTestId('logo-hyperliquid')).toBeInTheDocument()
    expect(screen.getByTestId('logo-bitunix')).toBeInTheDocument()
    expect(screen.getByTestId('logo-bingx')).toBeInTheDocument()
  })

  it('calls onExchangeTypeChange when exchange button is clicked', async () => {
    const onExchangeTypeChange = vi.fn()
    const user = userEvent.setup()

    render(
      <MemoryRouter>
        <BotBuilderStepExchange {...defaultProps} onExchangeTypeChange={onExchangeTypeChange} />
      </MemoryRouter>
    )

    await user.click(screen.getByTestId('logo-hyperliquid'))
    expect(onExchangeTypeChange).toHaveBeenCalledWith('hyperliquid')
  })

  it('renders mode buttons (Demo and Live)', () => {
    render(
      <MemoryRouter>
        <BotBuilderStepExchange {...defaultProps} />
      </MemoryRouter>
    )

    expect(screen.getByText('Demo')).toBeInTheDocument()
    expect(screen.getByText('Live')).toBeInTheDocument()
  })

  it('calls onModeChange when mode button is clicked', async () => {
    const onModeChange = vi.fn()
    const user = userEvent.setup()

    render(
      <MemoryRouter>
        <BotBuilderStepExchange {...defaultProps} onModeChange={onModeChange} />
      </MemoryRouter>
    )

    await user.click(screen.getByText('Live'))
    expect(onModeChange).toHaveBeenCalledWith('live')
  })

  it('renders margin mode buttons', () => {
    render(
      <MemoryRouter>
        <BotBuilderStepExchange {...defaultProps} />
      </MemoryRouter>
    )

    expect(screen.getByText('Cross')).toBeInTheDocument()
    expect(screen.getByText('Isolated')).toBeInTheDocument()
  })

  it('calls onMarginModeChange when margin mode button is clicked', async () => {
    const onMarginModeChange = vi.fn()
    const user = userEvent.setup()

    render(
      <MemoryRouter>
        <BotBuilderStepExchange {...defaultProps} onMarginModeChange={onMarginModeChange} />
      </MemoryRouter>
    )

    await user.click(screen.getByText('Isolated'))
    expect(onMarginModeChange).toHaveBeenCalledWith('isolated')
  })

  it('shows balance overview table when balance data is available', () => {
    const balanceOverview: BalancePreview[] = [
      {
        exchange_type: 'bitget',
        mode: 'demo',
        currency: 'USDT',
        exchange_balance: 10000,
        exchange_equity: 10000,
        existing_allocated_pct: 30,
        existing_allocated_amount: 3000,
        remaining_balance: 7000,
        has_connection: true,
        error: null,
      },
    ]

    render(
      <MemoryRouter>
        <BotBuilderStepExchange {...defaultProps} balanceOverview={balanceOverview} />
      </MemoryRouter>
    )

    // Should show the "All Exchanges" heading
    expect(screen.getByText('All Exchanges')).toBeInTheDocument()
  })

  it('shows loading state when overview is loading', () => {
    render(
      <MemoryRouter>
        <BotBuilderStepExchange {...defaultProps} overviewLoading={true} />
      </MemoryRouter>
    )

    // The loading skeleton has an animate-pulse class
    const loadingEl = document.querySelector('.animate-pulse')
    expect(loadingEl).toBeInTheDocument()
  })

  it('shows no connections warning when balance overview is empty', () => {
    render(
      <MemoryRouter>
        <BotBuilderStepExchange {...defaultProps} balanceOverview={[]} overviewLoading={false} />
      </MemoryRouter>
    )

    expect(screen.getByText('No connections')).toBeInTheDocument()
  })

  it('renders symbol search input', () => {
    render(
      <MemoryRouter>
        <BotBuilderStepExchange {...defaultProps} />
      </MemoryRouter>
    )

    expect(screen.getByPlaceholderText('Search symbols...')).toBeInTheDocument()
  })

  it('calls onTogglePair when popular pair button is clicked', async () => {
    const onTogglePair = vi.fn()
    const user = userEvent.setup()

    render(
      <MemoryRouter>
        <BotBuilderStepExchange {...defaultProps} onTogglePair={onTogglePair} />
      </MemoryRouter>
    )

    // BTC popular button should exist (symbol = BTCUSDT for bitget)
    await user.click(screen.getByText('BTC'))
    expect(onTogglePair).toHaveBeenCalledWith('BTCUSDT')
  })

  it('renders copy trading exchange component when strategy is copy_trading', () => {
    render(
      <MemoryRouter>
        <BotBuilderStepExchange
          {...defaultProps}
          strategyType="copy_trading"
          strategyParams={{ source_wallet: '0x123' }}
          onStrategyParamsChange={vi.fn()}
          onTradingPairsChange={vi.fn()}
        />
      </MemoryRouter>
    )

    expect(screen.getByTestId('copy-trading-exchange')).toBeInTheDocument()
  })

  it('shows selected trading pairs as chips with remove buttons', () => {
    render(
      <MemoryRouter>
        <BotBuilderStepExchange {...defaultProps} tradingPairs={['BTCUSDT', 'ETHUSDT']} />
      </MemoryRouter>
    )

    // Each selected pair has a remove button with aria-label
    expect(screen.getByRole('button', { name: 'Remove BTCUSDT' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Remove ETHUSDT' })).toBeInTheDocument()
  })
})
