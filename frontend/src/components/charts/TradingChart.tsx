/**
 * TradingChart Component
 *
 * Displays OHLC candlestick chart with trade markers using Recharts.
 * Fetches data from the /api/ohlc endpoint.
 */

import { useState, useEffect, useMemo } from 'react';
import {
  ComposedChart,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceDot,
  Bar,
  Cell,
} from 'recharts';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import axios from 'axios';

interface Trade {
  id: number;
  symbol: string;
  side: 'long' | 'short';
  entry_price: number;
  exit_price?: number;
  entry_time: string;
  exit_time?: string;
  pnl?: number;
  status: string;
}

interface OHLCData {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

interface TradingChartProps {
  symbol?: string;
  trades?: Trade[];
  height?: number;
  granularity?: string;
  limit?: number;
}

export function TradingChart({
  symbol = 'BTCUSDT',
  trades = [],
  height = 400,
  granularity = '1H',
  limit = 100,
}: TradingChartProps) {
  const [ohlcData, setOhlcData] = useState<OHLCData[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchOHLC = async () => {
      try {
        setLoading(true);
        setError(null);
        const response = await axios.get(`/api/ohlc/${symbol}`, {
          params: { granularity, limit },
        });
        setOhlcData(response.data.data || []);
      } catch (err: any) {
        console.error('Failed to fetch OHLC data:', err);
        setError(err.response?.data?.detail || 'Failed to load chart data');
      } finally {
        setLoading(false);
      }
    };

    fetchOHLC();
    // Refresh every 60 seconds
    const interval = setInterval(fetchOHLC, 60000);
    return () => clearInterval(interval);
  }, [symbol, granularity, limit]);

  const formatPrice = (value: number) => `$${value.toLocaleString()}`;

  const formatTime = (timestamp: number) => {
    const date = new Date(timestamp);
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: '2-digit' });
  };

  // Process data for candlestick chart
  const chartData = useMemo(() => {
    return ohlcData.map((candle) => {
      const isGreen = candle.close >= candle.open;
      // Find trades that match this candle's time window
      const candleTime = new Date(candle.time);
      const entryTrade = trades.find((t) => {
        const entryTime = new Date(t.entry_time);
        return Math.abs(entryTime.getTime() - candleTime.getTime()) < 3600000; // Within 1 hour
      });
      const exitTrade = trades.find((t) => {
        if (!t.exit_time) return false;
        const exitTime = new Date(t.exit_time);
        return Math.abs(exitTime.getTime() - candleTime.getTime()) < 3600000;
      });

      return {
        time: candle.time,
        timeFormatted: formatTime(candle.time),
        open: candle.open,
        high: candle.high,
        low: candle.low,
        close: candle.close,
        volume: candle.volume,
        isGreen,
        // For candlestick body
        bodyBottom: Math.min(candle.open, candle.close),
        bodyHeight: Math.abs(candle.close - candle.open),
        // For wick/shadow
        wickTop: candle.high,
        wickBottom: candle.low,
        // Trade markers
        entryPrice: entryTrade?.entry_price,
        entrySide: entryTrade?.side,
        exitPrice: exitTrade?.exit_price,
        exitPnl: exitTrade?.pnl,
      };
    });
  }, [ohlcData, trades]);

  // Calculate price domain with padding
  const [minPrice, maxPrice] = useMemo(() => {
    if (chartData.length === 0) return [0, 100];
    const lows = chartData.map((d) => d.low);
    const highs = chartData.map((d) => d.high);
    const min = Math.min(...lows);
    const max = Math.max(...highs);
    const padding = (max - min) * 0.05;
    return [min - padding, max + padding];
  }, [chartData]);

  const CustomTooltip = ({
    active,
    payload,
  }: {
    active?: boolean;
    payload?: Array<{ payload: (typeof chartData)[0] }>;
  }) => {
    if (!active || !payload?.length) return null;
    const data = payload[0].payload;

    return (
      <div className="bg-card border border-border rounded-lg p-3 shadow-lg">
        <p className="text-muted-foreground text-sm">{data.timeFormatted}</p>
        <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm mt-1">
          <span className="text-muted-foreground">Open:</span>
          <span className="font-medium">{formatPrice(data.open)}</span>
          <span className="text-muted-foreground">High:</span>
          <span className="font-medium text-profit">{formatPrice(data.high)}</span>
          <span className="text-muted-foreground">Low:</span>
          <span className="font-medium text-loss">{formatPrice(data.low)}</span>
          <span className="text-muted-foreground">Close:</span>
          <span className={`font-medium ${data.isGreen ? 'text-profit' : 'text-loss'}`}>
            {formatPrice(data.close)}
          </span>
        </div>
        {data.entryPrice && (
          <div className="mt-2 pt-2 border-t border-border">
            <span className={data.entrySide === 'long' ? 'text-profit' : 'text-loss'}>
              Entry ({data.entrySide?.toUpperCase()}): {formatPrice(data.entryPrice)}
            </span>
          </div>
        )}
        {data.exitPrice && (
          <div className="text-sm">
            <span className={(data.exitPnl || 0) >= 0 ? 'text-profit' : 'text-loss'}>
              Exit: {formatPrice(data.exitPrice)} ({(data.exitPnl || 0) >= 0 ? '+' : ''}
              {data.exitPnl?.toFixed(2)})
            </span>
          </div>
        )}
      </div>
    );
  };

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-lg flex items-center justify-between">
          <span>
            {symbol} Chart ({granularity})
          </span>
          <div className="flex gap-2 text-sm font-normal">
            {trades.length > 0 && (
              <span className="text-muted-foreground">
                {trades.length} trade{trades.length !== 1 ? 's' : ''}
              </span>
            )}
            {ohlcData.length > 0 && (
              <span className="text-muted-foreground">{ohlcData.length} candles</span>
            )}
          </div>
        </CardTitle>
      </CardHeader>
      <CardContent className="p-2">
        {loading ? (
          <div
            className="flex items-center justify-center text-muted-foreground"
            style={{ height }}
          >
            Loading chart data...
          </div>
        ) : error ? (
          <div className="flex items-center justify-center text-loss" style={{ height }}>
            {error}
          </div>
        ) : chartData.length === 0 ? (
          <div
            className="flex items-center justify-center text-muted-foreground"
            style={{ height }}
          >
            No price data available
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={height}>
            <ComposedChart data={chartData} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="priceGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#6366f1" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#6366f1" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis
                dataKey="timeFormatted"
                stroke="#9ca3af"
                fontSize={11}
                tickLine={false}
                interval="preserveStartEnd"
              />
              <YAxis
                tickFormatter={formatPrice}
                stroke="#9ca3af"
                fontSize={12}
                domain={[minPrice, maxPrice]}
                width={80}
              />
              <Tooltip content={<CustomTooltip />} />

              {/* Candlestick bodies as bars */}
              <Bar dataKey="bodyHeight" stackId="candle" barSize={8}>
                {chartData.map((entry, index) => (
                  <Cell
                    key={`body-${index}`}
                    fill={entry.isGreen ? '#22c55e' : '#ef4444'}
                    y={entry.bodyBottom}
                  />
                ))}
              </Bar>

              {/* Entry markers */}
              {chartData
                .filter((d) => d.entryPrice)
                .map((d, i) => (
                  <ReferenceDot
                    key={`entry-${i}`}
                    x={d.timeFormatted}
                    y={d.entryPrice!}
                    r={8}
                    fill={d.entrySide === 'long' ? '#22c55e' : '#ef4444'}
                    stroke="#fff"
                    strokeWidth={2}
                    label={{
                      value: d.entrySide === 'long' ? '▲' : '▼',
                      fill: '#fff',
                      fontSize: 10,
                    }}
                  />
                ))}

              {/* Exit markers */}
              {chartData
                .filter((d) => d.exitPrice)
                .map((d, i) => (
                  <ReferenceDot
                    key={`exit-${i}`}
                    x={d.timeFormatted}
                    y={d.exitPrice!}
                    r={8}
                    fill={(d.exitPnl || 0) >= 0 ? '#22c55e' : '#ef4444'}
                    stroke="#fff"
                    strokeWidth={2}
                    label={{ value: '×', fill: '#fff', fontSize: 12 }}
                  />
                ))}
            </ComposedChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  );
}
