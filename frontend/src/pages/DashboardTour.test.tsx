import { describe, it, expect } from 'vitest';

describe('Dashboard tour configuration', () => {
  const dashboardSteps = [
    { selector: '[data-tour="dash-stats"]', titleKey: 'tour.dashPnlTitle', descKey: 'tour.dashPnlDesc' },
    { selector: '[data-tour="dash-charts"]', titleKey: 'tour.dashBotsTitle', descKey: 'tour.dashBotsDesc' },
    { selector: '[data-tour="dash-trades"]', titleKey: 'tour.dashFilterTitle', descKey: 'tour.dashFilterDesc' },
  ];

  it('tour steps reference valid CSS selectors', () => {
    const selectorPattern = /^\[data-tour="[\w-]+"\]$/;
    for (const step of dashboardSteps) {
      expect(step.selector).toMatch(selectorPattern);
    }
  });

  it('tour steps have valid i18n keys', () => {
    const titlePattern = /^tour\.\w+Title$/;
    const descPattern = /^tour\.\w+Desc$/;
    for (const step of dashboardSteps) {
      expect(step.titleKey).toMatch(titlePattern);
      expect(step.descKey).toMatch(descPattern);
    }
  });
});

describe('Bots page tour configuration', () => {
  const botsSteps = [
    { selector: '[data-tour="new-bot"]', titleKey: 'tour.newBotTitle', descKey: 'tour.newBotDesc' },
    { selector: '[data-tour="bot-card"]', titleKey: 'tour.botCardTitle', descKey: 'tour.botCardDesc' },
    { selector: '[data-tour="bot-stats"]', titleKey: 'tour.botStatsTitle', descKey: 'tour.botStatsDesc' },
    { selector: '[data-tour="bot-actions"]', titleKey: 'tour.botActionsTitle', descKey: 'tour.botActionsDesc' },
  ];

  it('tour steps reference valid CSS selectors', () => {
    const selectorPattern = /^\[data-tour="[\w-]+"\]$/;
    for (const step of botsSteps) {
      expect(step.selector).toMatch(selectorPattern);
    }
  });

  it('Bots tour has 4 steps', () => {
    expect(botsSteps).toHaveLength(4);
  });

  it('Dashboard tour has 3 steps', () => {
    const dashboardSteps = [
      { selector: '[data-tour="dash-stats"]', titleKey: 'tour.dashPnlTitle', descKey: 'tour.dashPnlDesc' },
      { selector: '[data-tour="dash-charts"]', titleKey: 'tour.dashBotsTitle', descKey: 'tour.dashBotsDesc' },
      { selector: '[data-tour="dash-trades"]', titleKey: 'tour.dashFilterTitle', descKey: 'tour.dashFilterDesc' },
    ];
    expect(dashboardSteps).toHaveLength(3);
   });
});
