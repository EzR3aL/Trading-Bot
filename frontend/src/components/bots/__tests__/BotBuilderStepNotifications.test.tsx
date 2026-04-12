import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import BotBuilderStepNotifications from '../BotBuilderStepNotifications'

// Mock i18n
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => {
      const translations: Record<string, string> = {
        'settings.notifications': 'Notifications',
        'bots.builder.optional': 'Optional',
        'bots.builder.discordWebhook': 'Discord Webhook URL',
        'bots.builder.discordWebhookHint': 'Paste your Discord webhook URL',
        'bots.builder.discordSetupGuide': 'Go to channel settings > Integrations > Webhooks',
        'bots.builder.telegramToken': 'Telegram Bot Token',
        'bots.builder.telegramChatId': 'Telegram Chat ID',
        'bots.builder.telegramHint': 'Create a bot via @BotFather',
      }
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

const defaultProps = {
  discordWebhookUrl: '',
  telegramBotToken: '',
  telegramChatId: '',
  openNotif: null as string | null,
  onDiscordWebhookUrlChange: vi.fn(),
  onTelegramBotTokenChange: vi.fn(),
  onTelegramChatIdChange: vi.fn(),
  onOpenNotifChange: vi.fn(),
}

describe('BotBuilderStepNotifications', () => {
  it('renders all notification channel headers (Discord, Telegram)', () => {
    render(<BotBuilderStepNotifications {...defaultProps} />)

    expect(screen.getByText('Discord')).toBeInTheDocument()
    expect(screen.getByText('Telegram')).toBeInTheDocument()
  })

  it('renders the Notifications label', () => {
    render(<BotBuilderStepNotifications {...defaultProps} />)

    expect(screen.getByText('Notifications')).toBeInTheDocument()
  })

  it('calls onOpenNotifChange when Discord header is clicked', async () => {
    const onOpenNotifChange = vi.fn()
    const user = userEvent.setup()

    render(<BotBuilderStepNotifications {...defaultProps} onOpenNotifChange={onOpenNotifChange} />)

    await user.click(screen.getByText('Discord'))
    expect(onOpenNotifChange).toHaveBeenCalledWith('discord')
  })

  it('calls onOpenNotifChange with null when open channel is clicked again (close)', async () => {
    const onOpenNotifChange = vi.fn()
    const user = userEvent.setup()

    render(
      <BotBuilderStepNotifications
        {...defaultProps}
        openNotif="discord"
        onOpenNotifChange={onOpenNotifChange}
      />
    )

    await user.click(screen.getByText('Discord'))
    expect(onOpenNotifChange).toHaveBeenCalledWith(null)
  })

  it('shows Discord webhook URL input when discord is open', () => {
    render(<BotBuilderStepNotifications {...defaultProps} openNotif="discord" />)

    expect(screen.getByLabelText('Discord Webhook URL')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('https://discord.com/api/webhooks/...')).toBeInTheDocument()
  })

  it('calls onDiscordWebhookUrlChange when typing in Discord webhook field', async () => {
    const onDiscordWebhookUrlChange = vi.fn()
    const user = userEvent.setup()

    render(
      <BotBuilderStepNotifications
        {...defaultProps}
        openNotif="discord"
        onDiscordWebhookUrlChange={onDiscordWebhookUrlChange}
      />
    )

    await user.type(screen.getByLabelText('Discord Webhook URL'), 'h')
    expect(onDiscordWebhookUrlChange).toHaveBeenCalledWith('h')
  })

  it('shows Telegram inputs when telegram is open', () => {
    render(<BotBuilderStepNotifications {...defaultProps} openNotif="telegram" />)

    expect(screen.getByLabelText('Telegram Bot Token')).toBeInTheDocument()
    expect(screen.getByLabelText('Telegram Chat ID')).toBeInTheDocument()
  })

  it('calls onTelegramBotTokenChange when typing in Telegram token field', async () => {
    const onTelegramBotTokenChange = vi.fn()
    const user = userEvent.setup()

    render(
      <BotBuilderStepNotifications
        {...defaultProps}
        openNotif="telegram"
        onTelegramBotTokenChange={onTelegramBotTokenChange}
      />
    )

    await user.type(screen.getByLabelText('Telegram Bot Token'), '6')
    expect(onTelegramBotTokenChange).toHaveBeenCalledWith('6')
  })

  it('calls onTelegramChatIdChange when typing in Telegram chat ID field', async () => {
    const onTelegramChatIdChange = vi.fn()
    const user = userEvent.setup()

    render(
      <BotBuilderStepNotifications
        {...defaultProps}
        openNotif="telegram"
        onTelegramChatIdChange={onTelegramChatIdChange}
      />
    )

    await user.type(screen.getByLabelText('Telegram Chat ID'), '1')
    expect(onTelegramChatIdChange).toHaveBeenCalledWith('1')
  })

  it('does not show input fields when no notification channel is open', () => {
    render(<BotBuilderStepNotifications {...defaultProps} openNotif={null} />)

    // No input fields should be visible
    expect(screen.queryByLabelText('Discord Webhook URL')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Telegram Bot Token')).not.toBeInTheDocument()
  })

  it('shows check icon when Discord webhook URL is filled', () => {
    const { container } = render(
      <BotBuilderStepNotifications {...defaultProps} discordWebhookUrl="https://discord.com/api/webhooks/123/abc" />
    )

    // Check icon is rendered as an SVG with lucide's Check component
    // The check icon appears next to Discord when URL is filled
    const discordSection = container.querySelector('.text-emerald-400')
    expect(discordSection).toBeInTheDocument()
  })
})
