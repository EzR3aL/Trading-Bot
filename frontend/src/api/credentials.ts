/**
 * Credentials API client.
 *
 * Handles API credential management operations.
 */

import { api } from './auth';

// Types
export interface Credential {
  id: number;
  name: string;
  exchange: string;
  credential_type: 'live' | 'demo';
  api_key_masked: string;
  is_active: boolean;
  created_at: string | null;
  last_used: string | null;
}

export interface CredentialCreate {
  name: string;
  api_key: string;
  api_secret: string;
  passphrase: string;
  exchange?: string;
  credential_type?: 'live' | 'demo';
}

export interface CredentialUpdate {
  api_key?: string;
  api_secret?: string;
  passphrase?: string;
}

export interface CredentialTestResult {
  success: boolean;
  message: string;
  balance?: number;
  permissions?: string[];
}

// API functions
export async function listCredentials(
  credentialType?: string
): Promise<{ credentials: Credential[]; count: number }> {
  const params = credentialType ? { credential_type: credentialType } : {};
  const response = await api.get('/credentials', { params });
  return response.data;
}

export async function getCredential(id: number): Promise<Credential> {
  const response = await api.get(`/credentials/${id}`);
  return response.data;
}

export async function createCredential(
  data: CredentialCreate
): Promise<Credential> {
  const response = await api.post('/credentials', data);
  return response.data;
}

export async function updateCredential(
  id: number,
  data: CredentialUpdate
): Promise<{ message: string }> {
  const response = await api.put(`/credentials/${id}`, data);
  return response.data;
}

export async function deleteCredential(
  id: number,
  permanent: boolean = false
): Promise<{ message: string }> {
  const response = await api.delete(`/credentials/${id}`, {
    params: { permanent },
  });
  return response.data;
}

export async function testCredential(id: number): Promise<CredentialTestResult> {
  const response = await api.post(`/credentials/${id}/test`);
  return response.data;
}

export async function activateCredential(
  id: number
): Promise<{ message: string }> {
  const response = await api.post(`/credentials/${id}/activate`);
  return response.data;
}
