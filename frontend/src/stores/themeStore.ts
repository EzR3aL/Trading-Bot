import { create } from 'zustand'

export type Theme = 'dark' | 'light'

interface ThemeState {
  theme: Theme
  toggleTheme: () => void
}

const stored = localStorage.getItem('theme') as Theme | null
const initial: Theme = stored === 'light' ? 'light' : 'dark'

// Apply initial theme class immediately to prevent flash
document.documentElement.classList.toggle('light', initial === 'light')
document.documentElement.classList.toggle('dark', initial === 'dark')

export const useThemeStore = create<ThemeState>((set, get) => ({
  theme: initial,

  toggleTheme: () => {
    const next = get().theme === 'dark' ? 'light' : 'dark'
    localStorage.setItem('theme', next)
    document.documentElement.classList.toggle('light', next === 'light')
    document.documentElement.classList.toggle('dark', next === 'dark')
    set({ theme: next })
  },
}))
