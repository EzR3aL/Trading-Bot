/**
 * Authentication Context for React.
 *
 * Provides global auth state, login/logout actions, and auto-refresh.
 */

import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  ReactNode,
} from 'react';
import {
  login as apiLogin,
  register as apiRegister,
  logout as apiLogout,
  getProfile,
  refreshToken,
  isAuthenticated,
  clearTokens,
  LoginRequest,
  RegisterRequest,
  User,
} from '../api/auth';

interface AuthContextType {
  user: User | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  error: string | null;
  login: (credentials: LoginRequest) => Promise<boolean>;
  register: (userData: RegisterRequest) => Promise<boolean>;
  logout: () => Promise<void>;
  clearError: () => void;
}

const AuthContext = createContext<AuthContextType | null>(null);

// Token refresh interval (5 minutes before expiry, assuming 1 hour tokens)
const REFRESH_INTERVAL_MS = 55 * 60 * 1000;

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Load user profile on mount if authenticated
  useEffect(() => {
    async function loadUser() {
      if (isAuthenticated()) {
        try {
          const profile = await getProfile();
          setUser(profile);
        } catch (err) {
          // Token expired or invalid
          clearTokens();
        }
      }
      setIsLoading(false);
    }

    loadUser();
  }, []);

  // Set up auto-refresh
  useEffect(() => {
    if (!user) return;

    const interval = setInterval(async () => {
      const newToken = await refreshToken();
      if (!newToken) {
        // Refresh failed, log out
        setUser(null);
        clearTokens();
      }
    }, REFRESH_INTERVAL_MS);

    return () => clearInterval(interval);
  }, [user]);

  const login = useCallback(async (credentials: LoginRequest): Promise<boolean> => {
    setError(null);
    setIsLoading(true);

    try {
      const response = await apiLogin(credentials);
      setUser(response.user);
      return true;
    } catch (err: any) {
      const message =
        err.response?.data?.detail || 'Login failed. Please try again.';
      setError(message);
      return false;
    } finally {
      setIsLoading(false);
    }
  }, []);

  const register = useCallback(async (userData: RegisterRequest): Promise<boolean> => {
    setError(null);
    setIsLoading(true);

    try {
      const response = await apiRegister(userData);
      setUser(response.user);
      return true;
    } catch (err: any) {
      const message =
        err.response?.data?.detail || 'Registration failed. Please try again.';
      setError(message);
      return false;
    } finally {
      setIsLoading(false);
    }
  }, []);

  const logout = useCallback(async () => {
    setIsLoading(true);
    await apiLogout();
    setUser(null);
    setIsLoading(false);
  }, []);

  const clearError = useCallback(() => {
    setError(null);
  }, []);

  return (
    <AuthContext.Provider
      value={{
        user,
        isLoading,
        isAuthenticated: !!user,
        error,
        login,
        register,
        logout,
        clearError,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextType {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
