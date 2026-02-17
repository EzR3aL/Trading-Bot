import { describe, it, expect, beforeEach } from 'vitest'
import { useThemeStore } from '../themeStore'

describe('themeStore', () => {
  beforeEach(() => {
    localStorage.clear()
    // Reset to dark theme
    useThemeStore.setState({ theme: 'dark' })
    document.documentElement.classList.remove('light')
    document.documentElement.classList.add('dark')
  })

  it('should default to dark theme', () => {
    expect(useThemeStore.getState().theme).toBe('dark')
  })

  describe('toggleTheme', () => {
    it('should toggle from dark to light', () => {
      useThemeStore.getState().toggleTheme()

      const state = useThemeStore.getState()
      expect(state.theme).toBe('light')
      expect(localStorage.getItem('theme')).toBe('light')
      expect(document.documentElement.classList.contains('light')).toBe(true)
      expect(document.documentElement.classList.contains('dark')).toBe(false)
    })

    it('should toggle from light to dark', () => {
      useThemeStore.setState({ theme: 'light' })
      useThemeStore.getState().toggleTheme()

      const state = useThemeStore.getState()
      expect(state.theme).toBe('dark')
      expect(localStorage.getItem('theme')).toBe('dark')
      expect(document.documentElement.classList.contains('dark')).toBe(true)
      expect(document.documentElement.classList.contains('light')).toBe(false)
    })

    it('should toggle back and forth correctly', () => {
      useThemeStore.getState().toggleTheme()
      expect(useThemeStore.getState().theme).toBe('light')

      useThemeStore.getState().toggleTheme()
      expect(useThemeStore.getState().theme).toBe('dark')

      useThemeStore.getState().toggleTheme()
      expect(useThemeStore.getState().theme).toBe('light')
    })

    it('should persist theme to localStorage', () => {
      useThemeStore.getState().toggleTheme()
      expect(localStorage.getItem('theme')).toBe('light')

      useThemeStore.getState().toggleTheme()
      expect(localStorage.getItem('theme')).toBe('dark')
    })
  })
})
