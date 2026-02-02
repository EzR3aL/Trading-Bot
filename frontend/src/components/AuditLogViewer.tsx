/**
 * Audit Log Viewer Component.
 *
 * Displays audit logs with filtering capabilities.
 */

import React, { useState, useEffect } from 'react';
import { getAuditLogs, AuditLog } from '../api/admin';

const EVENT_TYPES = [
  { value: '', label: 'All Events' },
  { value: 'user.login', label: 'User Login' },
  { value: 'user.logout', label: 'User Logout' },
  { value: 'user.login_failed', label: 'Login Failed' },
  { value: 'user.register', label: 'User Registered' },
  { value: 'user.role_change', label: 'Role Changed' },
  { value: 'credential.create', label: 'Credential Created' },
  { value: 'credential.delete', label: 'Credential Deleted' },
  { value: 'bot.create', label: 'Bot Created' },
  { value: 'bot.start', label: 'Bot Started' },
  { value: 'bot.stop', label: 'Bot Stopped' },
  { value: 'trade.entry', label: 'Trade Entry' },
  { value: 'trade.exit', label: 'Trade Exit' },
];

const SEVERITY_COLORS: Record<string, string> = {
  info: 'bg-blue-100 text-blue-800',
  warning: 'bg-yellow-100 text-yellow-800',
  error: 'bg-red-100 text-red-800',
  critical: 'bg-red-200 text-red-900',
};

export function AuditLogViewer() {
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [eventTypeFilter, setEventTypeFilter] = useState('');
  const [expandedLog, setExpandedLog] = useState<number | null>(null);

  const loadLogs = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await getAuditLogs(
        undefined,
        eventTypeFilter || undefined,
        100
      );
      setLogs(data.logs);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to load audit logs');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadLogs();
  }, [eventTypeFilter]);

  const formatEventType = (type: string) => {
    return type
      .split('.')
      .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
      .join(' ');
  };

  const formatTimestamp = (ts: string) => {
    const date = new Date(ts);
    return date.toLocaleString();
  };

  if (isLoading && logs.length === 0) {
    return (
      <div className="flex justify-center py-8">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-600"></div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h2 className="text-xl font-bold text-gray-900">Audit Logs</h2>
        <div className="flex items-center gap-4">
          <select
            value={eventTypeFilter}
            onChange={(e) => setEventTypeFilter(e.target.value)}
            className="px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-indigo-500"
          >
            {EVENT_TYPES.map((type) => (
              <option key={type.value} value={type.value}>
                {type.label}
              </option>
            ))}
          </select>
          <button
            onClick={loadLogs}
            className="px-4 py-2 bg-indigo-600 text-white rounded-md hover:bg-indigo-700"
          >
            Refresh
          </button>
        </div>
      </div>

      {error && (
        <div className="p-3 rounded bg-red-100 border border-red-400 text-red-700">
          {error}
        </div>
      )}

      <div className="bg-white rounded-lg shadow overflow-hidden">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                Time
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                Event
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                User
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                IP Address
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                Severity
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                Status
              </th>
            </tr>
          </thead>
          <tbody className="bg-white divide-y divide-gray-200">
            {logs.map((log) => (
              <React.Fragment key={log.id}>
                <tr
                  className="hover:bg-gray-50 cursor-pointer"
                  onClick={() => setExpandedLog(expandedLog === log.id ? null : log.id)}
                >
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                    {formatTimestamp(log.timestamp)}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
                    {formatEventType(log.event_type)}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                    {log.user_id ? `User #${log.user_id}` : '-'}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 font-mono">
                    {log.ip_address || '-'}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <span
                      className={`px-2 py-1 text-xs rounded-full ${
                        SEVERITY_COLORS[log.severity] || 'bg-gray-100 text-gray-800'
                      }`}
                    >
                      {log.severity}
                    </span>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    {log.success ? (
                      <span className="text-green-600">Success</span>
                    ) : (
                      <span className="text-red-600">Failed</span>
                    )}
                  </td>
                </tr>
                {expandedLog === log.id && (
                  <tr>
                    <td colSpan={6} className="px-6 py-4 bg-gray-50">
                      <div className="text-sm">
                        <strong>Details:</strong>
                        <pre className="mt-2 p-2 bg-gray-100 rounded text-xs overflow-x-auto">
                          {JSON.stringify(log.details, null, 2)}
                        </pre>
                        {log.error_message && (
                          <div className="mt-2 text-red-600">
                            <strong>Error:</strong> {log.error_message}
                          </div>
                        )}
                        {log.resource_type && (
                          <div className="mt-2">
                            <strong>Resource:</strong> {log.resource_type} #{log.resource_id}
                          </div>
                        )}
                      </div>
                    </td>
                  </tr>
                )}
              </React.Fragment>
            ))}
          </tbody>
        </table>

        {logs.length === 0 && (
          <div className="text-center py-8 text-gray-500">No audit logs found</div>
        )}
      </div>
    </div>
  );
}
