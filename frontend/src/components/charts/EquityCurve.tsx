/**
 * EquityCurve Component
 *
 * Displays account equity over time using Recharts.
 */

import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from 'recharts';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';

interface EquityDataPoint {
  date: string;
  equity: number;
  pnl?: number;
}

interface EquityCurveProps {
  data: EquityDataPoint[];
  startingBalance?: number;
  height?: number;
  title?: string;
}

export function EquityCurve({
  data,
  startingBalance = 10000,
  height = 300,
  title = 'Equity Curve'
}: EquityCurveProps) {
  // Calculate if overall profitable
  const currentEquity = data.length > 0 ? data[data.length - 1].equity : startingBalance;
  const isProfitable = currentEquity >= startingBalance;
  const totalReturn = ((currentEquity - startingBalance) / startingBalance) * 100;

  // Find max drawdown
  let peak = startingBalance;
  let maxDrawdown = 0;
  data.forEach(d => {
    if (d.equity > peak) peak = d.equity;
    const drawdown = ((peak - d.equity) / peak) * 100;
    if (drawdown > maxDrawdown) maxDrawdown = drawdown;
  });

  const formatCurrency = (value: number) => `$${value.toLocaleString()}`;
  const formatDate = (date: string) => {
    const d = new Date(date);
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  };

  const CustomTooltip = ({ active, payload, label }: { active?: boolean; payload?: Array<{ value: number }>; label?: string }) => {
    if (!active || !payload?.length) return null;

    return (
      <div className="bg-card border border-border rounded-lg p-3 shadow-lg">
        <p className="text-muted-foreground text-sm">{formatDate(label || '')}</p>
        <p className="font-medium">{formatCurrency(payload[0].value)}</p>
      </div>
    );
  };

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-lg flex items-center justify-between">
          <span>{title}</span>
          <div className="flex gap-4 text-sm font-normal">
            <span className={isProfitable ? 'text-profit' : 'text-loss'}>
              {isProfitable ? '+' : ''}{totalReturn.toFixed(2)}%
            </span>
            <span className="text-muted-foreground">
              Max DD: {maxDrawdown.toFixed(2)}%
            </span>
          </div>
        </CardTitle>
      </CardHeader>
      <CardContent>
        {data.length === 0 ? (
          <div className="flex items-center justify-center text-muted-foreground" style={{ height }}>
            No data available
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={height}>
            <AreaChart data={data} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="equityGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop
                    offset="5%"
                    stopColor={isProfitable ? '#22c55e' : '#ef4444'}
                    stopOpacity={0.3}
                  />
                  <stop
                    offset="95%"
                    stopColor={isProfitable ? '#22c55e' : '#ef4444'}
                    stopOpacity={0}
                  />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis
                dataKey="date"
                tickFormatter={formatDate}
                stroke="#9ca3af"
                fontSize={12}
              />
              <YAxis
                tickFormatter={formatCurrency}
                stroke="#9ca3af"
                fontSize={12}
                domain={['auto', 'auto']}
              />
              <Tooltip content={<CustomTooltip />} />
              <ReferenceLine
                y={startingBalance}
                stroke="#6366f1"
                strokeDasharray="5 5"
              />
              <Area
                type="monotone"
                dataKey="equity"
                stroke={isProfitable ? '#22c55e' : '#ef4444'}
                strokeWidth={2}
                fill="url(#equityGradient)"
              />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  );
}
