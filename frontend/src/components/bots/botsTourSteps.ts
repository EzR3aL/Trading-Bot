import type { TourStep } from '../ui/GuidedTour'

export const botsTourSteps: TourStep[] = [
  {
    target: '[data-tour="new-bot"]',
    titleKey: 'tour.botsNewBotTitle',
    descriptionKey: 'tour.botsNewBotDesc',
    position: 'bottom',
  },
  {
    target: '[data-tour="bot-card"]',
    titleKey: 'tour.botsBotCardTitle',
    descriptionKey: 'tour.botsBotCardDesc',
    position: 'bottom',
  },
  {
    target: '[data-tour="bot-stats"]',
    titleKey: 'tour.botsStatsTitle',
    descriptionKey: 'tour.botsStatsDesc',
    position: 'top',
  },
  {
    target: '[data-tour="bot-actions"]',
    titleKey: 'tour.botsActionsTitle',
    descriptionKey: 'tour.botsActionsDesc',
    position: 'top',
  },
]
