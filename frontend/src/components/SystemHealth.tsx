/**
 * System Health Component.
 *
 * Displays system metrics and health status for admins.
 */

import { useState, useEffect } from 'react';
import { getSystemStats, SystemStats } from '../api/admin';

export function SystemHealth() {
  const [stats, setStats] = useState<SystemStats | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadStats = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await getSystemStats();
      setStats(data);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to load system stats');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadStats();
    // Refresh every 30 seconds
    const interval = setInterval(loadStats, 30000);
    return () => clearInterval(interval);
  }, []);

  if (isLoading && !stats) {
    return (
      <div className="flex justify-center py-8">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-600"></div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4 rounded bg-red-100 border border-red-400 text-red-700">
        {error}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-bold text-gray-900">System Health</h2>

      <div className="grid grid-cols-1 md:grid-cols-5 gap-4">
        <div className="bg-white rounded-lg shadow p-6">
          <div className="text-sm text-gray-500">Total Users</div>
          <div className="text-3xl font-bold text-gray-900">
            {stats?.total_users ?? '-'}
          </div>
        </div>

        <div className="bg-white rounded-lg shadow p-6">
          <div className="text-sm text-gray-500">Active Users</div>
          <div className="text-3xl font-bold text-green-600">
            {stats?.active_users ?? '-'}
          </div>
        </div>

        <div className="bg-white rounded-lg shadow p-6">
          <div className="text-sm text-gray-500">Total Bots</div>
          <div className="text-3xl font-bold text-gray-900">
            {stats?.total_bots ?? '-'}
          </div>
        </div>

        <div className="bg-white rounded-lg shadow p-6">
          <div className="text-sm text-gray-500">Active Bots</div>
          <div className="text-3xl font-bold text-green-600">
            {stats?.active_bots ?? '-'}
          </div>
        </div>

        <div className="bg-white rounded-lg shadow p-6">
          <div className="text-sm text-gray-500">Trades Today</div>
          <div className="text-3xl font-bold text-indigo-600">
            {stats?.total_trades_today ?? '-'}
          </div>
        </div>
      </div>

      <div className="bg-white rounded-lg shadow p-6">
        <h3 className="text-lg font-semibold mb-4">System Status</h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="flex items-center gap-3">
            <span className="h-3 w-3 rounded-full bg-green-500"></span>
            <span className="text-sm text-gray-600">API Server</span>
            <span className="text-sm text-green-600 ml-auto">Online</span>
          </div>
          <div className="flex items-center gap-3">
            <span className="h-3 w-3 rounded-full bg-green-500"></span>
            <span className="text-sm text-gray-600">Database</span>
            <span className="text-sm text-green-600 ml-auto">Connected</span>
          </div>
          <div className="flex items-center gap-3">
            <span className="h-3 w-3 rounded-full bg-green-500"></span>
            <span className="text-sm text-gray-600">WebSocket</span>
            <span className="text-sm text-green-600 ml-auto">Active</span>
          </div>
        </div>
      </div>
    </div>
  );
}
