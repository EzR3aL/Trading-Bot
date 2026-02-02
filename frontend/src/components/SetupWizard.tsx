/**
 * Setup Wizard Component
 *
 * Onboarding guide that walks users through bot setup and trading concepts.
 */

import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';

interface SetupWizardProps {
  onComplete: () => void;
  onSkip: () => void;
}

const WIZARD_COMPLETED_KEY = 'bitget_wizard_completed';

export function useWizardState() {
  const [showWizard, setShowWizard] = useState(false);

  useEffect(() => {
    const completed = localStorage.getItem(WIZARD_COMPLETED_KEY);
    if (!completed) {
      setShowWizard(true);
    }
  }, []);

  const completeWizard = () => {
    localStorage.setItem(WIZARD_COMPLETED_KEY, 'true');
    setShowWizard(false);
  };

  const resetWizard = () => {
    localStorage.removeItem(WIZARD_COMPLETED_KEY);
    setShowWizard(true);
  };

  return { showWizard, completeWizard, resetWizard, setShowWizard };
}

export function SetupWizard({ onComplete, onSkip }: SetupWizardProps) {
  const [step, setStep] = useState(0);

  const steps = [
    { title: 'Welcome', icon: '👋' },
    { title: 'API Setup', icon: '🔑' },
    { title: 'Configuration', icon: '⚙️' },
    { title: 'How Trading Works', icon: '📈' },
    { title: 'Risk Management', icon: '🛡️' },
    { title: 'Get Started', icon: '🚀' },
  ];

  const nextStep = () => {
    if (step < steps.length - 1) {
      setStep(step + 1);
    } else {
      onComplete();
    }
  };

  const prevStep = () => {
    if (step > 0) {
      setStep(step - 1);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <Card className="w-full max-w-2xl max-h-[90vh] overflow-hidden flex flex-col">
        {/* Progress bar */}
        <div className="h-1 bg-muted">
          <div
            className="h-full bg-primary transition-all duration-300"
            style={{ width: `${((step + 1) / steps.length) * 100}%` }}
          />
        </div>

        {/* Step indicators */}
        <div className="flex justify-center gap-2 py-4 border-b">
          {steps.map((s, i) => (
            <button
              key={i}
              onClick={() => setStep(i)}
              className={`w-8 h-8 rounded-full flex items-center justify-center text-sm transition-colors ${
                i === step
                  ? 'bg-primary text-primary-foreground'
                  : i < step
                    ? 'bg-primary/20 text-primary'
                    : 'bg-muted text-muted-foreground'
              }`}
              title={s.title}
            >
              {s.icon}
            </button>
          ))}
        </div>

        <CardHeader className="pb-2">
          <CardTitle className="text-xl flex items-center gap-2">
            <span className="text-2xl">{steps[step].icon}</span>
            {steps[step].title}
          </CardTitle>
        </CardHeader>

        <CardContent className="flex-1 overflow-y-auto">
          {step === 0 && <WelcomeStep />}
          {step === 1 && <ApiSetupStep />}
          {step === 2 && <ConfigurationStep />}
          {step === 3 && <HowTradingWorksStep />}
          {step === 4 && <RiskManagementStep />}
          {step === 5 && <GetStartedStep />}
        </CardContent>

        {/* Navigation */}
        <div className="flex justify-between items-center p-4 border-t bg-muted/50">
          <Button variant="ghost" onClick={onSkip}>
            Skip Tutorial
          </Button>
          <div className="flex gap-2">
            {step > 0 && (
              <Button variant="outline" onClick={prevStep}>
                Previous
              </Button>
            )}
            <Button onClick={nextStep}>
              {step === steps.length - 1 ? 'Finish' : 'Next'}
            </Button>
          </div>
        </div>
      </Card>
    </div>
  );
}

function WelcomeStep() {
  return (
    <div className="space-y-4">
      <p className="text-lg">
        Welcome to the <strong>Bitget Trading Bot Dashboard</strong>!
      </p>
      <p className="text-muted-foreground">
        This wizard will guide you through setting up your bot and help you understand how
        automated trading works.
      </p>

      <div className="bg-muted rounded-lg p-4 space-y-3">
        <h3 className="font-semibold">What this bot does:</h3>
        <ul className="space-y-2 text-sm">
          <li className="flex items-start gap-2">
            <span className="text-primary">✓</span>
            <span>Analyzes market sentiment and liquidation data</span>
          </li>
          <li className="flex items-start gap-2">
            <span className="text-primary">✓</span>
            <span>Identifies contrarian trading opportunities</span>
          </li>
          <li className="flex items-start gap-2">
            <span className="text-primary">✓</span>
            <span>Executes trades automatically with risk management</span>
          </li>
          <li className="flex items-start gap-2">
            <span className="text-primary">✓</span>
            <span>Tracks performance and generates reports</span>
          </li>
        </ul>
      </div>

      <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4 text-yellow-800 text-sm">
        <strong>Important:</strong> Trading cryptocurrencies involves significant risk. Only trade
        with funds you can afford to lose. Start with demo mode to understand how the bot works.
      </div>
    </div>
  );
}

function ApiSetupStep() {
  return (
    <div className="space-y-4">
      <p>
        To trade on Bitget, you need to connect your API credentials. This allows the bot to place
        trades on your behalf.
      </p>

      <div className="bg-muted rounded-lg p-4 space-y-3">
        <h3 className="font-semibold">How to get API credentials:</h3>
        <ol className="space-y-2 text-sm list-decimal list-inside">
          <li>
            Log in to{' '}
            <a
              href="https://www.bitget.com"
              target="_blank"
              rel="noopener noreferrer"
              className="text-primary underline"
            >
              Bitget.com
            </a>
          </li>
          <li>
            Go to <strong>Profile → API Management</strong>
          </li>
          <li>
            Click <strong>"Create API"</strong>
          </li>
          <li>
            Enable <strong>Trade</strong> and <strong>Read</strong> permissions
          </li>
          <li>
            <strong>Do NOT</strong> enable Withdraw permission
          </li>
          <li>Copy your API Key, Secret Key, and Passphrase</li>
        </ol>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div className="bg-green-50 border border-green-200 rounded-lg p-3">
          <h4 className="font-semibold text-green-800 text-sm mb-1">Demo Trading (Recommended)</h4>
          <p className="text-xs text-green-700">
            Use Bitget's demo account to practice without risking real money. Get demo API keys
            from the Demo Trading section.
          </p>
        </div>
        <div className="bg-red-50 border border-red-200 rounded-lg p-3">
          <h4 className="font-semibold text-red-800 text-sm mb-1">Live Trading</h4>
          <p className="text-xs text-red-700">
            Uses real funds. Only use after you understand the bot and are comfortable with the
            risks.
          </p>
        </div>
      </div>

      <div className="pt-2">
        <Link
          to="/dashboard/credentials"
          className="inline-flex items-center gap-2 text-primary hover:underline"
        >
          → Go to Credentials page to add your API keys
        </Link>
      </div>
    </div>
  );
}

function ConfigurationStep() {
  return (
    <div className="space-y-4">
      <p>
        The bot has several configurable parameters that control how it trades. Here's what each
        setting means:
      </p>

      <div className="space-y-3">
        <ConfigItem
          title="Trading Pairs"
          description="Which cryptocurrencies to trade (e.g., BTCUSDT, ETHUSDT)"
          example="Default: BTCUSDT"
        />
        <ConfigItem
          title="Leverage"
          description="Multiplier for your position size. Higher = more risk/reward"
          example="Default: 10x"
        />
        <ConfigItem
          title="Position Size"
          description="Percentage of your balance to use per trade"
          example="Default: 5% of balance"
        />
        <ConfigItem
          title="Take Profit"
          description="Automatically close winning trades at this profit level"
          example="Default: 2%"
        />
        <ConfigItem
          title="Stop Loss"
          description="Automatically close losing trades at this loss level"
          example="Default: 1%"
        />
        <ConfigItem
          title="Max Trades Per Day"
          description="Limits how many trades the bot can make daily"
          example="Default: 2 trades"
        />
      </div>

      <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 text-sm text-blue-800">
        <strong>Tip:</strong> Start with conservative settings (lower leverage, smaller position
        size) until you understand how the bot performs.
      </div>
    </div>
  );
}

function ConfigItem({
  title,
  description,
  example,
}: {
  title: string;
  description: string;
  example: string;
}) {
  return (
    <div className="bg-muted rounded-lg p-3">
      <div className="flex justify-between items-start">
        <div>
          <h4 className="font-medium text-sm">{title}</h4>
          <p className="text-xs text-muted-foreground">{description}</p>
        </div>
        <span className="text-xs bg-background px-2 py-1 rounded">{example}</span>
      </div>
    </div>
  );
}

function HowTradingWorksStep() {
  return (
    <div className="space-y-4">
      <p>
        This bot uses a <strong>contrarian liquidation hunting</strong> strategy. Here's how it
        works:
      </p>

      <div className="space-y-4">
        {/* Step 1 */}
        <div className="flex gap-3">
          <div className="w-8 h-8 rounded-full bg-primary text-primary-foreground flex items-center justify-center flex-shrink-0">
            1
          </div>
          <div>
            <h4 className="font-semibold">Market Analysis</h4>
            <p className="text-sm text-muted-foreground">
              The bot monitors market sentiment (Fear & Greed Index), funding rates, and
              long/short ratios to identify extreme conditions.
            </p>
          </div>
        </div>

        {/* Step 2 */}
        <div className="flex gap-3">
          <div className="w-8 h-8 rounded-full bg-primary text-primary-foreground flex items-center justify-center flex-shrink-0">
            2
          </div>
          <div>
            <h4 className="font-semibold">Signal Generation</h4>
            <p className="text-sm text-muted-foreground">
              When the market is extremely fearful (oversold) → Look for LONG opportunities.
              <br />
              When the market is extremely greedy (overbought) → Look for SHORT opportunities.
            </p>
          </div>
        </div>

        {/* Step 3 */}
        <div className="flex gap-3">
          <div className="w-8 h-8 rounded-full bg-primary text-primary-foreground flex items-center justify-center flex-shrink-0">
            3
          </div>
          <div>
            <h4 className="font-semibold">Trade Execution</h4>
            <p className="text-sm text-muted-foreground">
              When a high-confidence signal is generated, the bot opens a position with
              pre-configured take profit and stop loss levels.
            </p>
          </div>
        </div>

        {/* Step 4 */}
        <div className="flex gap-3">
          <div className="w-8 h-8 rounded-full bg-primary text-primary-foreground flex items-center justify-center flex-shrink-0">
            4
          </div>
          <div>
            <h4 className="font-semibold">Position Management</h4>
            <p className="text-sm text-muted-foreground">
              The position stays open until either the take profit or stop loss is hit, or
              market conditions change significantly.
            </p>
          </div>
        </div>
      </div>

      <div className="bg-muted rounded-lg p-4 mt-4">
        <h4 className="font-semibold text-sm mb-2">Trade Example:</h4>
        <div className="text-xs space-y-1 font-mono bg-background rounded p-2">
          <p>
            <span className="text-muted-foreground">Signal:</span> Fear & Greed = 15 (Extreme
            Fear)
          </p>
          <p>
            <span className="text-muted-foreground">Action:</span>{' '}
            <span className="text-green-600">LONG BTCUSDT</span>
          </p>
          <p>
            <span className="text-muted-foreground">Entry:</span> $42,000
          </p>
          <p>
            <span className="text-muted-foreground">Take Profit:</span> $42,840 (+2%)
          </p>
          <p>
            <span className="text-muted-foreground">Stop Loss:</span> $41,580 (-1%)
          </p>
        </div>
      </div>
    </div>
  );
}

function RiskManagementStep() {
  return (
    <div className="space-y-4">
      <p>
        The bot includes several safety features to protect your capital:
      </p>

      <div className="space-y-3">
        <RiskFeature
          icon="🛑"
          title="Daily Loss Limit"
          description="Trading stops automatically if daily losses exceed 5% of your balance"
        />
        <RiskFeature
          icon="📊"
          title="Max Trades Per Day"
          description="Limits overtrading by capping the number of trades per day"
        />
        <RiskFeature
          icon="⚡"
          title="Stop Loss on Every Trade"
          description="Every position has an automatic stop loss to limit downside"
        />
        <RiskFeature
          icon="🔒"
          title="Position Sizing"
          description="Only risks a small percentage of your balance per trade"
        />
        <RiskFeature
          icon="🎯"
          title="Confidence Threshold"
          description="Only takes trades when signal confidence is high enough"
        />
      </div>

      <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-red-800">
        <h4 className="font-semibold mb-1">⚠️ Important Warnings</h4>
        <ul className="text-sm space-y-1">
          <li>• Past performance does not guarantee future results</li>
          <li>• Crypto markets are highly volatile</li>
          <li>• Never invest more than you can afford to lose</li>
          <li>• The bot can and will have losing trades</li>
        </ul>
      </div>
    </div>
  );
}

function RiskFeature({
  icon,
  title,
  description,
}: {
  icon: string;
  title: string;
  description: string;
}) {
  return (
    <div className="flex gap-3 items-start bg-muted rounded-lg p-3">
      <span className="text-xl">{icon}</span>
      <div>
        <h4 className="font-medium text-sm">{title}</h4>
        <p className="text-xs text-muted-foreground">{description}</p>
      </div>
    </div>
  );
}

function GetStartedStep() {
  return (
    <div className="space-y-4">
      <p className="text-lg">You're ready to start trading!</p>

      <div className="bg-muted rounded-lg p-4">
        <h3 className="font-semibold mb-3">Quick Start Checklist:</h3>
        <div className="space-y-2">
          <ChecklistItem text="Add your Bitget API credentials" link="/dashboard/credentials" />
          <ChecklistItem text="Review and adjust trading configuration" />
          <ChecklistItem text="Start with Demo Mode to test" />
          <ChecklistItem text="Monitor your first few trades" />
          <ChecklistItem text="Check the dashboard regularly" />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <Link
          to="/dashboard/credentials"
          className="block p-4 bg-primary/10 rounded-lg hover:bg-primary/20 transition-colors"
        >
          <h4 className="font-semibold text-primary">🔑 Add Credentials</h4>
          <p className="text-xs text-muted-foreground mt-1">Connect your Bitget API</p>
        </Link>
        <Link
          to="/dashboard"
          className="block p-4 bg-primary/10 rounded-lg hover:bg-primary/20 transition-colors"
        >
          <h4 className="font-semibold text-primary">📊 View Dashboard</h4>
          <p className="text-xs text-muted-foreground mt-1">Monitor performance</p>
        </Link>
      </div>

      <div className="bg-green-50 border border-green-200 rounded-lg p-4 text-green-800">
        <h4 className="font-semibold mb-1">💡 Pro Tip</h4>
        <p className="text-sm">
          Use Demo Mode first to understand how the bot trades. Once you're comfortable, you can
          switch to Live Mode with real funds.
        </p>
      </div>

      <p className="text-center text-muted-foreground text-sm">
        You can re-open this guide anytime from the Help menu.
      </p>
    </div>
  );
}

function ChecklistItem({ text, link }: { text: string; link?: string }) {
  const content = (
    <div className="flex items-center gap-2">
      <div className="w-5 h-5 rounded border-2 border-muted-foreground/30" />
      <span className="text-sm">{text}</span>
    </div>
  );

  if (link) {
    return (
      <Link to={link} className="block hover:bg-background rounded p-1 -m-1">
        {content}
      </Link>
    );
  }

  return content;
}
