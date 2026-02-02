/**
 * Trading Configuration Component.
 *
 * Form for editing bot trading parameters with sliders/inputs.
 */

import { useState, useEffect } from 'react';
import { api } from '../api/auth';

interface RiskConfig {
  max_trades_per_day: number;
  daily_loss_limit_percent: number;
  position_size_percent: number;
  take_profit_percent: number;
  stop_loss_percent: number;
  leverage: number;
}

interface TradingConfigProps {
  botId: number;
  onSave?: () => void;
}

export function TradingConfig({ botId, onSave }: TradingConfigProps) {
  const [config, setConfig] = useState<RiskConfig>({
    max_trades_per_day: 2,
    daily_loss_limit_percent: 3.0,
    position_size_percent: 2.0,
    take_profit_percent: 2.0,
    stop_loss_percent: 1.0,
    leverage: 10,
  });
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  useEffect(() => {
    loadConfig();
  }, [botId]);

  const loadConfig = async () => {
    setIsLoading(true);
    try {
      const response = await api.get(`/bots/${botId}/risk`);
      setConfig(response.data.risk_config || config);
    } catch (err) {
      // Use default config if not found
    } finally {
      setIsLoading(false);
    }
  };

  const handleSave = async () => {
    setIsSaving(true);
    setError(null);
    setSuccessMessage(null);

    try {
      await api.put(`/bots/${botId}/risk`, config);
      setSuccessMessage('Configuration saved successfully');
      onSave?.();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to save configuration');
    } finally {
      setIsSaving(false);
    }
  };

  const handleChange = (field: keyof RiskConfig, value: number) => {
    setConfig((prev) => ({ ...prev, [field]: value }));
    setSuccessMessage(null);
  };

  if (isLoading) {
    return (
      <div className="flex justify-center py-8">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-600"></div>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-lg shadow p-6">
      <h3 className="text-lg font-semibold mb-6">Risk Configuration</h3>

      {error && (
        <div className="mb-4 p-3 rounded bg-red-100 border border-red-400 text-red-700">
          {error}
        </div>
      )}

      {successMessage && (
        <div className="mb-4 p-3 rounded bg-green-100 border border-green-400 text-green-700">
          {successMessage}
        </div>
      )}

      <div className="space-y-6">
        {/* Max Trades Per Day */}
        <div>
          <label className="flex justify-between text-sm font-medium text-gray-700 mb-2">
            <span>Max Trades Per Day</span>
            <span className="text-indigo-600">{config.max_trades_per_day}</span>
          </label>
          <input
            type="range"
            min="1"
            max="10"
            value={config.max_trades_per_day}
            onChange={(e) =>
              handleChange('max_trades_per_day', parseInt(e.target.value))
            }
            className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer"
          />
          <div className="flex justify-between text-xs text-gray-500 mt-1">
            <span>1</span>
            <span>10</span>
          </div>
        </div>

        {/* Daily Loss Limit */}
        <div>
          <label className="flex justify-between text-sm font-medium text-gray-700 mb-2">
            <span>Daily Loss Limit</span>
            <span className="text-indigo-600">{config.daily_loss_limit_percent}%</span>
          </label>
          <input
            type="range"
            min="1"
            max="10"
            step="0.5"
            value={config.daily_loss_limit_percent}
            onChange={(e) =>
              handleChange('daily_loss_limit_percent', parseFloat(e.target.value))
            }
            className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer"
          />
          <div className="flex justify-between text-xs text-gray-500 mt-1">
            <span>1%</span>
            <span>10%</span>
          </div>
        </div>

        {/* Position Size */}
        <div>
          <label className="flex justify-between text-sm font-medium text-gray-700 mb-2">
            <span>Position Size</span>
            <span className="text-indigo-600">{config.position_size_percent}%</span>
          </label>
          <input
            type="range"
            min="0.5"
            max="10"
            step="0.5"
            value={config.position_size_percent}
            onChange={(e) =>
              handleChange('position_size_percent', parseFloat(e.target.value))
            }
            className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer"
          />
          <div className="flex justify-between text-xs text-gray-500 mt-1">
            <span>0.5%</span>
            <span>10%</span>
          </div>
        </div>

        {/* Take Profit */}
        <div>
          <label className="flex justify-between text-sm font-medium text-gray-700 mb-2">
            <span>Take Profit</span>
            <span className="text-green-600">{config.take_profit_percent}%</span>
          </label>
          <input
            type="range"
            min="0.5"
            max="10"
            step="0.5"
            value={config.take_profit_percent}
            onChange={(e) =>
              handleChange('take_profit_percent', parseFloat(e.target.value))
            }
            className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer"
          />
          <div className="flex justify-between text-xs text-gray-500 mt-1">
            <span>0.5%</span>
            <span>10%</span>
          </div>
        </div>

        {/* Stop Loss */}
        <div>
          <label className="flex justify-between text-sm font-medium text-gray-700 mb-2">
            <span>Stop Loss</span>
            <span className="text-red-600">{config.stop_loss_percent}%</span>
          </label>
          <input
            type="range"
            min="0.5"
            max="5"
            step="0.25"
            value={config.stop_loss_percent}
            onChange={(e) =>
              handleChange('stop_loss_percent', parseFloat(e.target.value))
            }
            className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer"
          />
          <div className="flex justify-between text-xs text-gray-500 mt-1">
            <span>0.5%</span>
            <span>5%</span>
          </div>
        </div>

        {/* Leverage */}
        <div>
          <label className="flex justify-between text-sm font-medium text-gray-700 mb-2">
            <span>Leverage</span>
            <span className="text-indigo-600">{config.leverage}x</span>
          </label>
          <input
            type="range"
            min="1"
            max="50"
            value={config.leverage}
            onChange={(e) => handleChange('leverage', parseInt(e.target.value))}
            className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer"
          />
          <div className="flex justify-between text-xs text-gray-500 mt-1">
            <span>1x</span>
            <span>50x</span>
          </div>
          {config.leverage > 20 && (
            <p className="text-xs text-yellow-600 mt-1">
              High leverage increases liquidation risk
            </p>
          )}
        </div>

        {/* Risk Summary */}
        <div className="p-4 bg-gray-50 rounded-lg">
          <h4 className="text-sm font-medium text-gray-700 mb-2">Risk Summary</h4>
          <div className="grid grid-cols-2 gap-2 text-sm">
            <div>
              <span className="text-gray-500">Max Daily Loss:</span>
              <span className="ml-2 font-medium">
                {config.daily_loss_limit_percent}% of balance
              </span>
            </div>
            <div>
              <span className="text-gray-500">Risk per Trade:</span>
              <span className="ml-2 font-medium">
                ~{(config.position_size_percent * config.stop_loss_percent / 100).toFixed(2)}%
              </span>
            </div>
            <div>
              <span className="text-gray-500">Risk/Reward:</span>
              <span className="ml-2 font-medium">
                1:{(config.take_profit_percent / config.stop_loss_percent).toFixed(1)}
              </span>
            </div>
            <div>
              <span className="text-gray-500">Liquidation at:</span>
              <span className="ml-2 font-medium">
                ~{(100 / config.leverage).toFixed(1)}% move
              </span>
            </div>
          </div>
        </div>

        <button
          onClick={handleSave}
          disabled={isSaving}
          className="w-full py-2 bg-indigo-600 text-white rounded-md hover:bg-indigo-700 disabled:bg-indigo-400"
        >
          {isSaving ? 'Saving...' : 'Save Configuration'}
        </button>
      </div>
    </div>
  );
}
