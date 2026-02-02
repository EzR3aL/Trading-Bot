/**
 * Credential List Component.
 *
 * Displays list of API credentials with actions.
 */

import { useState, useEffect } from 'react';
import {
  listCredentials,
  deleteCredential,
  testCredential,
  activateCredential,
  Credential,
} from '../api/credentials';
import { CredentialForm } from './CredentialForm';
import { ConfirmModal } from './ConfirmModal';

export function CredentialList() {
  const [credentials, setCredentials] = useState<Credential[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showAddForm, setShowAddForm] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Credential | null>(null);
  const [testingId, setTestingId] = useState<number | null>(null);
  const [testResult, setTestResult] = useState<{
    id: number;
    success: boolean;
    message: string;
  } | null>(null);

  const loadCredentials = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await listCredentials();
      setCredentials(data.credentials);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to load credentials');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadCredentials();
  }, []);

  const handleDelete = async (permanent: boolean) => {
    if (!deleteTarget) return;

    try {
      await deleteCredential(deleteTarget.id, permanent);
      setDeleteTarget(null);
      loadCredentials();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to delete credential');
    }
  };

  const handleTest = async (id: number) => {
    setTestingId(id);
    setTestResult(null);
    try {
      const result = await testCredential(id);
      setTestResult({ id, ...result });
    } catch (err: any) {
      setTestResult({
        id,
        success: false,
        message: err.response?.data?.detail || 'Test failed',
      });
    } finally {
      setTestingId(null);
    }
  };

  const handleActivate = async (id: number) => {
    try {
      await activateCredential(id);
      loadCredentials();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to activate credential');
    }
  };

  if (isLoading) {
    return (
      <div className="flex justify-center py-8">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-600"></div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h2 className="text-xl font-bold text-gray-900">API Credentials</h2>
        <button
          onClick={() => setShowAddForm(true)}
          className="px-4 py-2 bg-indigo-600 text-white rounded-md hover:bg-indigo-700"
        >
          Add Credential
        </button>
      </div>

      {error && (
        <div className="p-3 rounded bg-red-100 border border-red-400 text-red-700">
          {error}
          <button
            onClick={() => setError(null)}
            className="ml-2 text-red-700 hover:text-red-900"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Instructions Card */}
      <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-4">
        <h3 className="text-blue-800 font-semibold mb-2">How to Generate Bitget API Credentials</h3>
        <ol className="text-sm text-blue-700 list-decimal list-inside space-y-2">
          <li>Log in to your <a href="https://www.bitget.com" target="_blank" rel="noopener noreferrer" className="underline font-medium">Bitget account</a></li>
          <li>Go to <strong>Profile → API Management</strong> (or visit <a href="https://www.bitget.com/account/newapi" target="_blank" rel="noopener noreferrer" className="underline">bitget.com/account/newapi</a>)</li>
          <li>Click <strong>"Create API"</strong> and complete security verification</li>
          <li>Set a memorable name (e.g., "Trading Bot")</li>
          <li>
            <strong>Important Permissions:</strong>
            <ul className="list-disc list-inside ml-4 mt-1">
              <li>Enable <strong>"Trade"</strong> permission for futures trading</li>
              <li>Enable <strong>"Read"</strong> permission to view positions</li>
              <li>Do NOT enable "Withdraw" for security</li>
            </ul>
          </li>
          <li>Set IP whitelist (optional but recommended for security)</li>
          <li>Copy your <strong>API Key</strong>, <strong>Secret Key</strong>, and <strong>Passphrase</strong></li>
        </ol>
        <div className="mt-3 p-2 bg-yellow-100 border border-yellow-300 rounded text-yellow-800 text-xs">
          <strong>Security Tips:</strong> Never share your API secret. For demo trading, use the Bitget Demo account API keys instead of live keys.
          <br />
          Demo API: <a href="https://www.bitget.com/copytrading/demo-trading" target="_blank" rel="noopener noreferrer" className="underline">bitget.com/copytrading/demo-trading</a>
        </div>
      </div>

      {credentials.length === 0 ? (
        <div className="bg-white rounded-lg shadow p-6 text-center">
          <p className="text-gray-500 mb-4">No API credentials configured</p>
          <button
            onClick={() => setShowAddForm(true)}
            className="px-4 py-2 bg-indigo-600 text-white rounded-md hover:bg-indigo-700"
          >
            Add Your First Credential
          </button>
        </div>
      ) : (
        <div className="bg-white rounded-lg shadow overflow-hidden">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Name
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Type
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  API Key
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Status
                </th>
                <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {credentials.map((cred) => (
                <tr key={cred.id}>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <div className="text-sm font-medium text-gray-900">
                      {cred.name}
                    </div>
                    {cred.last_used && (
                      <div className="text-xs text-gray-500">
                        Last used: {new Date(cred.last_used).toLocaleDateString()}
                      </div>
                    )}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <span
                      className={`px-2 py-1 text-xs rounded-full ${
                        cred.credential_type === 'live'
                          ? 'bg-red-100 text-red-800'
                          : 'bg-green-100 text-green-800'
                      }`}
                    >
                      {cred.credential_type.toUpperCase()}
                    </span>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <code className="text-sm text-gray-500 font-mono">
                      {cred.api_key_masked}
                    </code>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    {cred.is_active ? (
                      <span className="text-green-600">Active</span>
                    ) : (
                      <span className="text-gray-400">Inactive</span>
                    )}
                    {testResult && testResult.id === cred.id && (
                      <div
                        className={`text-xs mt-1 ${
                          testResult.success ? 'text-green-600' : 'text-red-600'
                        }`}
                      >
                        {testResult.message}
                      </div>
                    )}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-right text-sm">
                    <button
                      onClick={() => handleTest(cred.id)}
                      disabled={testingId === cred.id}
                      className="text-indigo-600 hover:text-indigo-900 mr-3 disabled:text-gray-400"
                    >
                      {testingId === cred.id ? 'Testing...' : 'Test'}
                    </button>
                    {!cred.is_active && (
                      <button
                        onClick={() => handleActivate(cred.id)}
                        className="text-green-600 hover:text-green-900 mr-3"
                      >
                        Activate
                      </button>
                    )}
                    <button
                      onClick={() => setDeleteTarget(cred)}
                      className="text-red-600 hover:text-red-900"
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showAddForm && (
        <CredentialForm
          onSuccess={() => {
            setShowAddForm(false);
            loadCredentials();
          }}
          onCancel={() => setShowAddForm(false)}
        />
      )}

      {deleteTarget && (
        <ConfirmModal
          title="Delete Credential"
          message={`Are you sure you want to delete "${deleteTarget.name}"?`}
          confirmLabel="Delete"
          confirmVariant="danger"
          onConfirm={() => handleDelete(false)}
          onCancel={() => setDeleteTarget(null)}
        />
      )}
    </div>
  );
}
