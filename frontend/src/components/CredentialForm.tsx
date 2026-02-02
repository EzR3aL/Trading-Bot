/**
 * Credential Form Component.
 *
 * Form for adding new API credentials with validation.
 */

import { useState, FormEvent } from 'react';
import { createCredential } from '../api/credentials';

interface CredentialFormProps {
  onSuccess: () => void;
  onCancel: () => void;
}

export function CredentialForm({ onSuccess, onCancel }: CredentialFormProps) {
  const [name, setName] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [apiSecret, setApiSecret] = useState('');
  const [passphrase, setPassphrase] = useState('');
  const [credentialType, setCredentialType] = useState<'live' | 'demo'>('demo');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Real-time validation
  const [nameError, setNameError] = useState<string | null>(null);
  const [apiKeyError, setApiKeyError] = useState<string | null>(null);
  const [apiSecretError, setApiSecretError] = useState<string | null>(null);
  const [passphraseError, setPassphraseError] = useState<string | null>(null);

  const validateName = (value: string) => {
    if (!value.trim()) {
      setNameError('Name is required');
      return false;
    }
    if (!/^[a-zA-Z0-9\s_-]+$/.test(value)) {
      setNameError('Name can only contain letters, numbers, spaces, underscores, and hyphens');
      return false;
    }
    if (value.length > 100) {
      setNameError('Name must be 100 characters or less');
      return false;
    }
    setNameError(null);
    return true;
  };

  const validateApiKey = (value: string) => {
    if (!value.trim()) {
      setApiKeyError('API Key is required');
      return false;
    }
    if (value.length < 10) {
      setApiKeyError('API Key must be at least 10 characters');
      return false;
    }
    setApiKeyError(null);
    return true;
  };

  const validateApiSecret = (value: string) => {
    if (!value.trim()) {
      setApiSecretError('API Secret is required');
      return false;
    }
    if (value.length < 10) {
      setApiSecretError('API Secret must be at least 10 characters');
      return false;
    }
    setApiSecretError(null);
    return true;
  };

  const validatePassphrase = (value: string) => {
    if (!value.trim()) {
      setPassphraseError('Passphrase is required');
      return false;
    }
    if (value.length < 4) {
      setPassphraseError('Passphrase must be at least 4 characters');
      return false;
    }
    setPassphraseError(null);
    return true;
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);

    // Validate all fields
    const isNameValid = validateName(name);
    const isApiKeyValid = validateApiKey(apiKey);
    const isApiSecretValid = validateApiSecret(apiSecret);
    const isPassphraseValid = validatePassphrase(passphrase);

    if (!isNameValid || !isApiKeyValid || !isApiSecretValid || !isPassphraseValid) {
      return;
    }

    setIsLoading(true);

    try {
      await createCredential({
        name: name.trim(),
        api_key: apiKey.trim(),
        api_secret: apiSecret.trim(),
        passphrase: passphrase.trim(),
        exchange: 'bitget',
        credential_type: credentialType,
      });
      onSuccess();
    } catch (err: any) {
      const message = err.response?.data?.detail || 'Failed to create credential';
      setError(message);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg p-6 max-w-md w-full mx-4 max-h-[90vh] overflow-y-auto">
        <h2 className="text-xl font-bold mb-4">Add API Credential</h2>

        {error && (
          <div className="mb-4 p-3 rounded bg-red-100 border border-red-400 text-red-700">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Name
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => {
                setName(e.target.value);
                validateName(e.target.value);
              }}
              onBlur={() => validateName(name)}
              className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-indigo-500 ${
                nameError ? 'border-red-400' : 'border-gray-300'
              }`}
              placeholder="My Trading Keys"
              disabled={isLoading}
            />
            {nameError && (
              <p className="mt-1 text-xs text-red-600">{nameError}</p>
            )}
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Type
            </label>
            <div className="flex gap-4">
              <label className="flex items-center">
                <input
                  type="radio"
                  value="demo"
                  checked={credentialType === 'demo'}
                  onChange={(e) => setCredentialType(e.target.value as 'demo')}
                  className="h-4 w-4 text-indigo-600"
                  disabled={isLoading}
                />
                <span className="ml-2 text-sm text-gray-700">Demo (Paper Trading)</span>
              </label>
              <label className="flex items-center">
                <input
                  type="radio"
                  value="live"
                  checked={credentialType === 'live'}
                  onChange={(e) => setCredentialType(e.target.value as 'live')}
                  className="h-4 w-4 text-indigo-600"
                  disabled={isLoading}
                />
                <span className="ml-2 text-sm text-gray-700">Live (Real Money)</span>
              </label>
            </div>
            {credentialType === 'live' && (
              <p className="mt-1 text-xs text-yellow-600">
                Warning: Live credentials will trade real money!
              </p>
            )}
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              API Key
            </label>
            <input
              type="text"
              value={apiKey}
              onChange={(e) => {
                setApiKey(e.target.value);
                validateApiKey(e.target.value);
              }}
              onBlur={() => validateApiKey(apiKey)}
              className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-indigo-500 font-mono ${
                apiKeyError ? 'border-red-400' : 'border-gray-300'
              }`}
              placeholder="bg_xxxxx..."
              disabled={isLoading}
            />
            {apiKeyError && (
              <p className="mt-1 text-xs text-red-600">{apiKeyError}</p>
            )}
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              API Secret
            </label>
            <input
              type="password"
              value={apiSecret}
              onChange={(e) => {
                setApiSecret(e.target.value);
                validateApiSecret(e.target.value);
              }}
              onBlur={() => validateApiSecret(apiSecret)}
              className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-indigo-500 font-mono ${
                apiSecretError ? 'border-red-400' : 'border-gray-300'
              }`}
              placeholder="••••••••••"
              disabled={isLoading}
            />
            {apiSecretError && (
              <p className="mt-1 text-xs text-red-600">{apiSecretError}</p>
            )}
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Passphrase
            </label>
            <input
              type="password"
              value={passphrase}
              onChange={(e) => {
                setPassphrase(e.target.value);
                validatePassphrase(e.target.value);
              }}
              onBlur={() => validatePassphrase(passphrase)}
              className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-indigo-500 ${
                passphraseError ? 'border-red-400' : 'border-gray-300'
              }`}
              placeholder="••••••••"
              disabled={isLoading}
            />
            {passphraseError && (
              <p className="mt-1 text-xs text-red-600">{passphraseError}</p>
            )}
          </div>

          <div className="flex justify-end gap-3 pt-4">
            <button
              type="button"
              onClick={onCancel}
              className="px-4 py-2 text-gray-700 hover:bg-gray-100 rounded-md"
              disabled={isLoading}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="px-4 py-2 bg-indigo-600 text-white rounded-md hover:bg-indigo-700 disabled:bg-indigo-400"
              disabled={isLoading}
            >
              {isLoading ? 'Adding...' : 'Add Credential'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
