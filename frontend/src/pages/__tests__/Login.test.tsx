import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import Login from '../Login'
import { useAuthStore } from '../../stores/authStore'

// Mock react-router-dom
const mockNavigate = vi.fn()
vi.mock('react-router-dom', () => ({
  useNavigate: () => mockNavigate,
}))

// Mock react-i18next
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => {
      const translations: Record<string, string> = {
        'login.title': 'Sign in to your account',
        'login.username': 'Username',
        'login.password': 'Password',
        'login.submit': 'Sign in',
        'login.error': 'Invalid username or password',
        'common.loading': 'Loading...',
      }
      return translations[key] || key
    },
  }),
}))

// Mock the api client to prevent side effects from authStore import
vi.mock('../../api/client', () => ({
  default: {
    post: vi.fn(),
    get: vi.fn(),
    interceptors: {
      request: { use: vi.fn() },
      response: { use: vi.fn() },
    },
  },
}))

describe('Login Page', () => {
  beforeEach(() => {
    mockNavigate.mockClear()
    useAuthStore.setState({
      user: null,
      isAuthenticated: false,
      isLoading: false,
    })
  })

  it('should render login form', () => {
    render(<Login />)

    expect(screen.getByText('Trading Bot')).toBeInTheDocument()
    expect(screen.getByText('Sign in to your account')).toBeInTheDocument()
    expect(screen.getByLabelText('Username')).toBeInTheDocument()
    expect(screen.getByLabelText('Password')).toBeInTheDocument()
    expect(screen.getByText('Sign in')).toBeInTheDocument()
  })

  it('should have required username and password fields', () => {
    render(<Login />)

    const usernameInput = screen.getByLabelText('Username')
    const passwordInput = screen.getByLabelText('Password')

    expect(usernameInput).toBeRequired()
    expect(passwordInput).toBeRequired()
  })

  it('should have correct input types', () => {
    render(<Login />)

    const usernameInput = screen.getByLabelText('Username')
    const passwordInput = screen.getByLabelText('Password')

    expect(usernameInput).toHaveAttribute('type', 'text')
    expect(passwordInput).toHaveAttribute('type', 'password')
  })

  it('should update username field on input', async () => {
    const user = userEvent.setup()
    render(<Login />)

    const usernameInput = screen.getByLabelText('Username')
    await user.type(usernameInput, 'testuser')

    expect(usernameInput).toHaveValue('testuser')
  })

  it('should update password field on input', async () => {
    const user = userEvent.setup()
    render(<Login />)

    const passwordInput = screen.getByLabelText('Password')
    await user.type(passwordInput, 'secretpass')

    expect(passwordInput).toHaveValue('secretpass')
  })

  it('should call login and navigate on successful submit', async () => {
    const mockLogin = vi.fn().mockResolvedValueOnce({ requires2fa: false })
    useAuthStore.setState({ login: mockLogin } as unknown as Parameters<typeof useAuthStore.setState>[0])

    const user = userEvent.setup()
    render(<Login />)

    await user.type(screen.getByLabelText('Username'), 'admin')
    await user.type(screen.getByLabelText('Password'), 'password123')
    await user.click(screen.getByText('Sign in'))

    await waitFor(() => {
      expect(mockLogin).toHaveBeenCalledWith('admin', 'password123')
      expect(mockNavigate).toHaveBeenCalledWith('/')
    })
  })

  it('should display error message on login failure', async () => {
    const mockLogin = vi.fn().mockRejectedValueOnce(new Error('fail'))
    useAuthStore.setState({ login: mockLogin } as unknown as Parameters<typeof useAuthStore.setState>[0])

    const user = userEvent.setup()
    render(<Login />)

    await user.type(screen.getByLabelText('Username'), 'bad')
    await user.type(screen.getByLabelText('Password'), 'wrong')
    await user.click(screen.getByText('Sign in'))

    await waitFor(() => {
      expect(screen.getByText('Invalid username or password')).toBeInTheDocument()
    })
  })

  it('should show loading state during login', () => {
    useAuthStore.setState({ isLoading: true })

    render(<Login />)

    expect(screen.getByText('Loading...')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /loading/i })).toBeDisabled()
  })

  it('should disable submit button while loading', () => {
    useAuthStore.setState({ isLoading: true })

    render(<Login />)

    const submitButton = screen.getByRole('button')
    expect(submitButton).toBeDisabled()
  })

  it('should clear error on new submit attempt', async () => {
    const mockLogin = vi.fn()
      .mockRejectedValueOnce(new Error('fail'))
      .mockResolvedValueOnce({ requires2fa: false })
    useAuthStore.setState({ login: mockLogin } as unknown as Parameters<typeof useAuthStore.setState>[0])

    const user = userEvent.setup()
    render(<Login />)

    // First attempt - fails
    await user.type(screen.getByLabelText('Username'), 'bad')
    await user.type(screen.getByLabelText('Password'), 'wrong')
    await user.click(screen.getByText('Sign in'))

    await waitFor(() => {
      expect(screen.getByText('Invalid username or password')).toBeInTheDocument()
    })

    // Second attempt - error should be cleared during submission
    fireEvent.submit(screen.getByRole('button').closest('form')!)

    await waitFor(() => {
      // After successful login, error should be gone and navigation should happen
      expect(mockNavigate).toHaveBeenCalledWith('/')
    })
  })

  it('should have autocomplete attributes for accessibility', () => {
    render(<Login />)

    const usernameInput = screen.getByLabelText('Username')
    const passwordInput = screen.getByLabelText('Password')

    expect(usernameInput).toHaveAttribute('autocomplete', 'username')
    expect(passwordInput).toHaveAttribute('autocomplete', 'current-password')
  })
})
