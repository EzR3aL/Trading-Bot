/**
 * Admin API client.
 *
 * Handles admin-only operations for user management and system monitoring.
 */

import { api } from './auth';

// Types
export interface AdminUser {
  id: number;
  username: string;
  email: string;
  is_active: boolean;
  is_admin: boolean;
  role: string;
  created_at: string | null;
  updated_at: string | null;
  last_login: string | null;
}

export interface SystemStats {
  total_users: number;
  active_users: number;
  total_bots: number;
  active_bots: number;
  total_trades_today: number;
}

export interface AuditLog {
  id: number;
  event_type: string;
  user_id: number | null;
  ip_address: string | null;
  severity: string;
  details: Record<string, any>;
  timestamp: string;
  resource_type: string | null;
  resource_id: number | null;
  success: boolean;
  error_message: string | null;
}

// API functions
export async function listUsers(
  includeInactive: boolean = false,
  limit: number = 100
): Promise<{ users: AdminUser[]; count: number; total: number }> {
  const response = await api.get('/admin/users', {
    params: { include_inactive: includeInactive, limit },
  });
  return response.data;
}

export async function getUser(userId: number): Promise<AdminUser> {
  const response = await api.get(`/admin/users/${userId}`);
  return response.data;
}

export async function updateUserRole(
  userId: number,
  role: string
): Promise<{ message: string }> {
  const response = await api.put(`/admin/users/${userId}/role`, { role });
  return response.data;
}

export async function updateUserStatus(
  userId: number,
  isActive: boolean
): Promise<{ message: string }> {
  const response = await api.put(`/admin/users/${userId}/status`, {
    is_active: isActive,
  });
  return response.data;
}

export async function deleteUser(
  userId: number,
  permanent: boolean = false
): Promise<{ message: string }> {
  const response = await api.delete(`/admin/users/${userId}`, {
    params: { permanent },
  });
  return response.data;
}

export async function getSystemStats(): Promise<SystemStats> {
  const response = await api.get('/admin/stats');
  return response.data;
}

export async function getAuditLogs(
  userId?: number,
  eventType?: string,
  limit: number = 100
): Promise<{ logs: AuditLog[]; count: number }> {
  const params: Record<string, any> = { limit };
  if (userId) params.user_id = userId;
  if (eventType) params.event_type = eventType;

  const response = await api.get('/admin/audit-logs', { params });
  return response.data;
}
