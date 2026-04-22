import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import GuidedTour, { type TourStep } from '../components/ui/GuidedTour';
import { useTourStore } from '../stores/tourStore';

/* ── Static tour configuration checks (pre-existing) ────────── */

describe('Dashboard tour configuration', () => {
  const dashboardSteps = [
    { selector: '[data-tour="dash-stats"]', titleKey: 'tour.dashPnlTitle', descKey: 'tour.dashPnlDesc' },
    { selector: '[data-tour="dash-charts"]', titleKey: 'tour.dashChartsTitle', descKey: 'tour.dashChartsDesc' },
    { selector: '[data-tour="dash-trades"]', titleKey: 'tour.dashTradesTitle', descKey: 'tour.dashTradesDesc' },
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
      { selector: '[data-tour="dash-charts"]', titleKey: 'tour.dashChartsTitle', descKey: 'tour.dashChartsDesc' },
      { selector: '[data-tour="dash-trades"]', titleKey: 'tour.dashTradesTitle', descKey: 'tour.dashTradesDesc' },
    ];
    expect(dashboardSteps).toHaveLength(3);
  });
});

/* ── autoStart gating behaviour (UX-M3) ─────────────────────── */

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => {
      const map: Record<string, string> = {
        'tour.skip': 'Skip',
        'tour.next': 'Next',
        'tour.prev': 'Back',
        'tour.done': 'Done',
        'tour.dashPnlTitle': 'Dashboard PnL',
        'tour.dashPnlDesc': 'Your profit and loss overview.',
        'tour.dashChartsTitle': 'Charts',
        'tour.dashChartsDesc': 'Your charts.',
        'tour.dashTradesTitle': 'Trades',
        'tour.dashTradesDesc': 'Your recent trades.',
      };
      return map[key] || key;
    },
  }),
}));

const dashboardTourSteps: TourStep[] = [
  {
    target: '[data-tour="dash-stats"]',
    titleKey: 'tour.dashPnlTitle',
    descriptionKey: 'tour.dashPnlDesc',
    position: 'bottom',
  },
  {
    target: '[data-tour="dash-charts"]',
    titleKey: 'tour.dashChartsTitle',
    descriptionKey: 'tour.dashChartsDesc',
    position: 'bottom',
  },
  {
    target: '[data-tour="dash-trades"]',
    titleKey: 'tour.dashTradesTitle',
    descriptionKey: 'tour.dashTradesDesc',
    position: 'top',
  },
];

function renderWithTargets(ready: boolean) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <div data-tour="dash-stats" style={{ width: 200, height: 50 }}>
          Stats
        </div>
        <div data-tour="dash-charts" style={{ width: 200, height: 50 }}>
          Charts
        </div>
        <div data-tour="dash-trades" style={{ width: 200, height: 50 }}>
          Trades
        </div>
        <GuidedTour tourId="dashboard" steps={dashboardTourSteps} autoStart={ready} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('Dashboard tour autoStart gating on ready state', () => {
  beforeEach(() => {
    localStorage.clear();
    useTourStore.setState({
      completedTours: {},
      activeTour: null,
    });
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('does not auto-start while dashboard queries are pending', () => {
    // ready=false simulates queries still in flight
    renderWithTargets(false);

    // Advance well past the 600ms auto-start delay
    act(() => {
      vi.advanceTimersByTime(2000);
    });

    expect(screen.queryByText('Dashboard PnL')).not.toBeInTheDocument();
    expect(useTourStore.getState().activeTour).toBeNull();
  });

  it('auto-starts the tour once dashboard queries succeed (ready=true)', () => {
    // ready=true simulates all queries resolved with data
    renderWithTargets(true);

    act(() => {
      vi.advanceTimersByTime(600);
    });

    expect(screen.getByText('Dashboard PnL')).toBeInTheDocument();
    expect(useTourStore.getState().activeTour).toBe('dashboard');
  });

  it('respects completed-tour flag even when ready=true (no re-autostart)', () => {
    useTourStore.setState({
      completedTours: { dashboard: true },
      activeTour: null,
    });

    renderWithTargets(true);

    act(() => {
      vi.advanceTimersByTime(2000);
    });

    expect(screen.queryByText('Dashboard PnL')).not.toBeInTheDocument();
  });
});
