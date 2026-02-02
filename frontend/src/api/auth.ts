/**
 * Authentication API client.
 *
 * Handles login, registration, token refresh, and logout.
 */

import axios, { AxiosError } from 'axios';

const API_BASE = '/api/auth';

// Token storage keys
const ACCESS_TOKEN_KEY = 'access_token';
const REFRESH_TOKEN_KEY = 'refresh_token';

// API client with interceptors for auto-refresh
const api = axios.create({
  baseURL: API_BASE,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Add access token to requests
api.interceptors.request.use((config) => {
  const token = localStorage.getItem(ACCESS_TOKEN_KEY);
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Handle token refresh on 401
api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config;

    if (
      error.response?.status === 401 &&
      originalRequest &&
      !(originalRequest as any)._retry
    ) {
      (originalRequest as any)._retry = true;

      try {
        const newToken = await refreshToken();
        if (newToken) {
          originalRequest.headers.Authorization = `Bearer ${newToken}`;
          return api(originalRequest);
        }
      } catch (refreshError) {
        // Refresh failed, clear tokens and redirect to login
        clearTokens();
        window.location.href = '/login';
        return Promise.reject(refreshError);
      }
    }

    return Promise.reject(error);
  }
);

// Types
export interface LoginRequest {
  username: string;
  password: string;
}

export interface RegisterRequest {
  username: string;
  email: string;
  password: string;
}

export interface AuthResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  user: {
    id: number;
    username: string;
    email: string;
    is_admin: boolean;
    role: string;
  };
}

export interface User {
  id: number;
  username: string;
  email: string;
  is_admin: boolean;
  role: string;
  created_at?: string;
  last_login?: string | null;
}

export interface ApiError {
  detail: string;
}

// Token management
export function getAccessToken(): string | null {
  return localStorage.getItem(ACCESS_TOKEN_KEY);
}

export function getRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_TOKEN_KEY);
}

export function setTokens(accessToken: string, refreshToken: string): void {
  localStorage.setItem(ACCESS_TOKEN_KEY, accessToken);
  localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
}

export function clearTokens(): void {
  localStorage.removeItem(ACCESS_TOKEN_KEY);
  localStorage.removeItem(REFRESH_TOKEN_KEY);
}

export function isAuthenticated(): boolean {
  return !!getAccessToken();
}

// API functions
export async function login(credentials: LoginRequest): Promise<AuthResponse> {
  const response = await api.post<Omit<AuthResponse, 'user'>>('/login', credentials);
  const data = response.data;

  setTokens(data.access_token, data.refresh_token);

  // Fetch user profile after login
  const user = await getProfile();

  return { ...data, user };
}

export async function register(
  userData: RegisterRequest
): Promise<AuthResponse> {
  const response = await api.post<Omit<AuthResponse, 'user'>>('/register', userData);
  const data = response.data;

  setTokens(data.access_token, data.refresh_token);

  // Fetch user profile after registration
  const user = await getProfile();

  return { ...data, user };
}

export async function refreshToken(): Promise<string | null> {
  const refresh = getRefreshToken();
  if (!refresh) {
    return null;
  }

  try {
    const response = await axios.post<AuthResponse>(`${API_BASE}/refresh`, {
      refresh_token: refresh,
    });

    const data = response.data;
    setTokens(data.access_token, data.refresh_token);

    return data.access_token;
  } catch (error) {
    clearTokens();
    return null;
  }
}

export async function logout(): Promise<void> {
  try {
    await api.post('/logout');
  } catch (error) {
    // Ignore errors on logout
  } finally {
    clearTokens();
  }
}

export async function getProfile(): Promise<User> {
  const response = await api.get<User>('/me');
  return response.data;
}

export async function updateEmail(newEmail: string): Promise<User> {
  const response = await api.put<User>('/me', {
    email: newEmail,
  });
  return response.data;
}

export async function updatePassword(
  currentPassword: string,
  newPassword: string
): Promise<User> {
  const response = await api.put<User>('/me', {
    current_password: currentPassword,
    new_password: newPassword,
  });
  return response.data;
}

// Export api instance for other modules
export { api };
