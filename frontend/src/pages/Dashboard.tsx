/**
 * Dashboard Page Component.
 *
 * Main authenticated interface for the trading bot.
 */

import React, { useEffect, useState } from 'react';
import { Routes, Route, Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { CredentialList } from '../components/CredentialList';
import { EquityCurve, PnLChart, TradingChart } from '../components/charts';
import { SetupWizard, useWizardState } from '../components/SetupWizard';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import axios from 'axios';

interface Trade {
  id: number;
  symbol: string;
  side: 'long' | 'short';
  size: number;
  entry_price: number;
  exit_price?: number;
  take_profit: number;
  stop_loss: number;
  leverage: number;
  confidence: number;
  reason: string;
  status: string;
  pnl?: number;
  pnl_percent?: number;
  fees?: number;
  entry_time: string;
  exit_time?: string;
}

interface DailyStats {
  date: string;
  net_pnl: number;
  trades_executed: number;
  winning_trades: number;
  losing_trades: number;
  win_rate: number;
}

interface Stats {
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  win_rate: number;
  total_pnl: number;
  total_fees: number;
  net_pnl: number;
  best_trade: number;
  worst_trade: number;
  avg_trade: number;
}

function Overview() {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [dailyStats, setDailyStats] = useState<DailyStats[]>([]);
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState<any>(null);

  useEffect(() => {
    async function fetchData() {
      try {
        const [tradesRes, statsRes, dailyRes, statusRes] = await Promise.all([
          axios.get('/api/trades?limit=50'),
          axios.get('/api/statistics?days=30'),
          axios.get('/api/performance/daily?days=30'),
          axios.get('/api/status'),
        ]);

        setTrades(tradesRes.data.trades || []);
        setStats(statsRes.data.trade_stats || null);
        setDailyStats(dailyRes.data.daily_stats || []);
        setStatus(statusRes.data);
      } catch (error) {
        console.error('Failed to fetch dashboard data:', error);
      } finally {
        setLoading(false);
      }
    }

    fetchData();
    const interval = setInterval(fetchData, 30000); // Refresh every 30s
    return () => clearInterval(interval);
  }, []);

  // Build equity curve data
  const equityData = React.useMemo(() => {
    let equity = 10000; // Starting balance
    return dailyStats.map(d => {
      equity += d.net_pnl || 0;
      return { date: d.date, equity, pnl: d.net_pnl };
    });
  }, [dailyStats]);

  // Get closed trades for PnL chart
  const closedTrades = trades.filter(t => t.status === 'closed' && t.pnl !== undefined);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <span className="text-muted-foreground">Loading dashboard...</span>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold">Overview</h2>
        {status?.demo_mode && (
          <Badge variant="outline" className="bg-orange-100 text-orange-800 border-orange-300">
            Demo Mode
          </Badge>
        )}
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <Card>
          <CardContent className="p-6">
            <div className="text-sm text-muted-foreground">Total P&L (30d)</div>
            <div className={`text-2xl font-bold ${(stats?.net_pnl || 0) >= 0 ? 'text-profit' : 'text-loss'}`}>
              {(stats?.net_pnl || 0) >= 0 ? '+' : ''}${(stats?.net_pnl || 0).toFixed(2)}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-6">
            <div className="text-sm text-muted-foreground">Win Rate</div>
            <div className="text-2xl font-bold">{(stats?.win_rate || 0).toFixed(1)}%</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-6">
            <div className="text-sm text-muted-foreground">Total Trades</div>
            <div className="text-2xl font-bold">{stats?.total_trades || 0}</div>
            <div className="text-xs text-muted-foreground">
              {stats?.winning_trades || 0}W / {stats?.losing_trades || 0}L
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-6">
            <div className="text-sm text-muted-foreground">Fees Paid</div>
            <div className="text-2xl font-bold text-loss">
              -${(stats?.total_fees || 0).toFixed(2)}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Price Chart */}
      <TradingChart
        symbol={status?.config?.trading_pairs?.[0] || 'BTCUSDT'}
        trades={trades}
        height={350}
        granularity="1H"
        limit={50}
      />

      {/* Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <EquityCurve data={equityData} startingBalance={10000} />
        <PnLChart trades={closedTrades.filter(t => t.pnl !== undefined).slice(0, 20).map(t => ({ ...t, pnl: t.pnl! }))} />
      </div>

      {/* Open Positions */}
      <Card>
        <CardHeader>
          <CardTitle>Open Positions</CardTitle>
        </CardHeader>
        <CardContent>
          {trades.filter(t => t.status === 'open').length === 0 ? (
            <p className="text-muted-foreground">No open positions</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="border-b">
                    <th className="text-left py-2 px-2">Symbol</th>
                    <th className="text-left py-2 px-2">Side</th>
                    <th className="text-right py-2 px-2">Size</th>
                    <th className="text-right py-2 px-2">Entry</th>
                    <th className="text-right py-2 px-2">TP / SL</th>
                    <th className="text-right py-2 px-2">Leverage</th>
                  </tr>
                </thead>
                <tbody>
                  {trades.filter(t => t.status === 'open').map(trade => (
                    <tr key={trade.id} className="border-b">
                      <td className="py-2 px-2 font-medium">{trade.symbol}</td>
                      <td className="py-2 px-2">
                        <Badge variant={trade.side === 'long' ? 'default' : 'destructive'}>
                          {trade.side.toUpperCase()}
                        </Badge>
                      </td>
                      <td className="py-2 px-2 text-right">{trade.size.toFixed(4)}</td>
                      <td className="py-2 px-2 text-right">${trade.entry_price.toFixed(2)}</td>
                      <td className="py-2 px-2 text-right text-sm">
                        <span className="text-profit">${trade.take_profit.toFixed(2)}</span>
                        {' / '}
                        <span className="text-loss">${trade.stop_loss.toFixed(2)}</span>
                      </td>
                      <td className="py-2 px-2 text-right">{trade.leverage}x</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Recent Trades */}
      <Card>
        <CardHeader>
          <CardTitle>Recent Trades</CardTitle>
        </CardHeader>
        <CardContent>
          {closedTrades.length === 0 ? (
            <p className="text-muted-foreground">No closed trades yet</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="border-b">
                    <th className="text-left py-2 px-2">Time</th>
                    <th className="text-left py-2 px-2">Symbol</th>
                    <th className="text-left py-2 px-2">Side</th>
                    <th className="text-right py-2 px-2">Entry</th>
                    <th className="text-right py-2 px-2">Exit</th>
                    <th className="text-right py-2 px-2">P&L</th>
                    <th className="text-right py-2 px-2">Fees</th>
                  </tr>
                </thead>
                <tbody>
                  {closedTrades.slice(0, 10).map(trade => (
                    <tr key={trade.id} className="border-b">
                      <td className="py-2 px-2 text-sm">
                        {trade.exit_time ? new Date(trade.exit_time).toLocaleString() : '-'}
                      </td>
                      <td className="py-2 px-2 font-medium">{trade.symbol}</td>
                      <td className="py-2 px-2">
                        <Badge variant={trade.side === 'long' ? 'default' : 'destructive'}>
                          {trade.side.toUpperCase()}
                        </Badge>
                      </td>
                      <td className="py-2 px-2 text-right">${trade.entry_price.toFixed(2)}</td>
                      <td className="py-2 px-2 text-right">${trade.exit_price?.toFixed(2) || '-'}</td>
                      <td className={`py-2 px-2 text-right font-medium ${(trade.pnl || 0) >= 0 ? 'text-profit' : 'text-loss'}`}>
                        {(trade.pnl || 0) >= 0 ? '+' : ''}${(trade.pnl || 0).toFixed(2)}
                      </td>
                      <td className="py-2 px-2 text-right text-muted-foreground">
                        ${(trade.fees || 0).toFixed(2)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function Bots() {
  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <h2 className="text-2xl font-bold">Trading Bots</h2>
        <Link
          to="/dashboard/bots/new"
          className="px-4 py-2 bg-primary text-primary-foreground rounded-md hover:bg-primary/90"
        >
          Create Bot
        </Link>
      </div>
      <Card>
        <CardContent className="p-6">
          <p className="text-muted-foreground">No bots configured yet</p>
        </CardContent>
      </Card>
    </div>
  );
}

function Credentials() {
  return <CredentialList />;
}

function Settings() {
  const { user } = useAuth();

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold">Account Settings</h2>
      <Card>
        <CardHeader>
          <CardTitle>Profile</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <label className="block text-sm text-muted-foreground">Username</label>
            <p>{user?.username}</p>
          </div>
          <div>
            <label className="block text-sm text-muted-foreground">Email</label>
            <p>{user?.email}</p>
          </div>
          <div>
            <label className="block text-sm text-muted-foreground">Role</label>
            <p className="capitalize">{user?.role || 'trader'}</p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

export function Dashboard() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const { showWizard, completeWizard, setShowWizard } = useWizardState();

  const handleLogout = async () => {
    await logout();
    navigate('/login');
  };

  return (
    <div className="min-h-screen bg-background">
      {/* Setup Wizard */}
      {showWizard && (
        <SetupWizard
          onComplete={completeWizard}
          onSkip={completeWizard}
        />
      )}

      {/* Navigation */}
      <nav className="bg-primary text-primary-foreground border-b">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-16">
            <div className="flex items-center">
              <span className="text-xl font-bold">Bitget Trading Bot</span>
              <div className="hidden md:block ml-10">
                <div className="flex items-baseline space-x-4">
                  <Link
                    to="/dashboard"
                    className="px-3 py-2 rounded-md text-sm font-medium hover:bg-primary/80"
                  >
                    Overview
                  </Link>
                  <Link
                    to="/dashboard/bots"
                    className="px-3 py-2 rounded-md text-sm font-medium hover:bg-primary/80"
                  >
                    Bots
                  </Link>
                  <Link
                    to="/dashboard/credentials"
                    className="px-3 py-2 rounded-md text-sm font-medium hover:bg-primary/80"
                  >
                    Credentials
                  </Link>
                  <Link
                    to="/dashboard/settings"
                    className="px-3 py-2 rounded-md text-sm font-medium hover:bg-primary/80"
                  >
                    Settings
                  </Link>
                </div>
              </div>
            </div>

            <div className="flex items-center space-x-4">
              {/* Help Button */}
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setShowWizard(true)}
                className="text-primary-foreground hover:bg-primary-foreground/10"
                title="Open Setup Guide"
              >
                <span className="mr-1">?</span> Help
              </Button>

              <span className="text-sm">
                {user?.username}
                {user?.is_admin && (
                  <Badge variant="secondary" className="ml-2">
                    Admin
                  </Badge>
                )}
              </span>
              {user?.is_admin && (
                <Link
                  to="/admin"
                  className="px-3 py-2 rounded-md text-sm font-medium bg-secondary text-secondary-foreground hover:bg-secondary/80"
                >
                  Admin Panel
                </Link>
              )}
              <button
                onClick={handleLogout}
                className="px-3 py-2 rounded-md text-sm font-medium bg-primary-foreground/10 hover:bg-primary-foreground/20"
              >
                Logout
              </button>
            </div>
          </div>
        </div>
      </nav>

      {/* Main content */}
      <main className="max-w-7xl mx-auto py-6 px-4 sm:px-6 lg:px-8">
        <Routes>
          <Route index element={<Overview />} />
          <Route path="bots" element={<Bots />} />
          <Route path="credentials" element={<Credentials />} />
          <Route path="settings" element={<Settings />} />
        </Routes>
      </main>
    </div>
  );
}
