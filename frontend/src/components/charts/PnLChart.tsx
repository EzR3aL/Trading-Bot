/**
 * PnLChart Component
 *
 * Displays profit/loss for each trade as a bar chart.
 */

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
  ReferenceLine,
} from 'recharts';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';

interface Trade {
  id: number;
  symbol: string;
  side: 'long' | 'short';
  pnl: number;
  pnl_percent?: number;
  entry_time: string;
  exit_time?: string;
}

interface PnLChartProps {
  trades: Trade[];
  height?: number;
  title?: string;
  showPercent?: boolean;
}

export function PnLChart({
  trades,
  height = 250,
  title = 'Trade P&L',
  showPercent = false
}: PnLChartProps) {
  // Prepare data
  const data = trades.map((trade) => ({
    id: trade.id,
    name: `#${trade.id}`,
    symbol: trade.symbol,
    side: trade.side,
    pnl: trade.pnl,
    pnl_percent: trade.pnl_percent || 0,
    date: trade.exit_time || trade.entry_time,
  }));

  // Calculate stats
  const totalPnL = trades.reduce((sum, t) => sum + t.pnl, 0);
  const winners = trades.filter(t => t.pnl > 0).length;
  const winRate = trades.length > 0 ? (winners / trades.length) * 100 : 0;

  const formatCurrency = (value: number) =>
    `${value >= 0 ? '+' : ''}$${value.toFixed(2)}`;

  const formatPercent = (value: number) =>
    `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`;

  const CustomTooltip = ({ active, payload }: { active?: boolean; payload?: Array<{ payload: typeof data[0] }> }) => {
    if (!active || !payload?.length) return null;
    const item = payload[0].payload;

    return (
      <div className="bg-card border border-border rounded-lg p-3 shadow-lg">
        <p className="font-medium">{item.symbol} #{item.id}</p>
        <p className="text-sm text-muted-foreground capitalize">{item.side}</p>
        <p className={item.pnl >= 0 ? 'text-profit' : 'text-loss'}>
          {formatCurrency(item.pnl)}
          {item.pnl_percent !== 0 && ` (${formatPercent(item.pnl_percent)})`}
        </p>
      </div>
    );
  };

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-lg flex items-center justify-between">
          <span>{title}</span>
          <div className="flex gap-4 text-sm font-normal">
            <span className={totalPnL >= 0 ? 'text-profit' : 'text-loss'}>
              Total: {formatCurrency(totalPnL)}
            </span>
            <span className="text-muted-foreground">
              Win Rate: {winRate.toFixed(1)}%
            </span>
          </div>
        </CardTitle>
      </CardHeader>
      <CardContent>
        {data.length === 0 ? (
          <div className="flex items-center justify-center text-muted-foreground" style={{ height }}>
            No trades to display
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={height}>
            <BarChart data={data} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" vertical={false} />
              <XAxis
                dataKey="name"
                stroke="#9ca3af"
                fontSize={12}
                tickLine={false}
              />
              <YAxis
                tickFormatter={showPercent ? formatPercent : formatCurrency}
                stroke="#9ca3af"
                fontSize={12}
                domain={['auto', 'auto']}
              />
              <Tooltip content={<CustomTooltip />} />
              <ReferenceLine y={0} stroke="#6366f1" strokeWidth={1} />
              <Bar
                dataKey={showPercent ? 'pnl_percent' : 'pnl'}
                radius={[4, 4, 0, 0]}
              >
                {data.map((entry, index) => (
                  <Cell
                    key={`cell-${index}`}
                    fill={entry.pnl >= 0 ? '#22c55e' : '#ef4444'}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  );
}
