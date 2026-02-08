/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        primary: {
          50: '#eff6ff',
          100: '#dbeafe',
          200: '#bfdbfe',
          300: '#93c5fd',
          400: '#60a5fa',
          500: '#3b82f6',
          600: '#2563eb',
          700: '#1d4ed8',
          800: '#1e40af',
          900: '#1e3a8a',
        },
        profit: '#00e676',
        loss: '#ff5252',
        surface: {
          DEFAULT: 'rgba(255, 255, 255, 0.03)',
          hover: 'rgba(255, 255, 255, 0.06)',
          active: 'rgba(255, 255, 255, 0.08)',
        },
      },
      backgroundImage: {
        'gradient-dark': 'linear-gradient(135deg, #0a0e17 0%, #111827 50%, #0f172a 100%)',
        'gradient-card': 'linear-gradient(135deg, rgba(255,255,255,0.05) 0%, rgba(255,255,255,0.02) 100%)',
        'gradient-sidebar': 'linear-gradient(180deg, #0d1321 0%, #111827 50%, #0a0e17 100%)',
        'gradient-accent': 'linear-gradient(135deg, #2563eb 0%, #3b82f6 50%, #60a5fa 100%)',
        'gradient-profit': 'linear-gradient(135deg, #00e676 0%, #00c853 100%)',
        'gradient-loss': 'linear-gradient(135deg, #ff5252 0%, #ff1744 100%)',
      },
      boxShadow: {
        glow: '0 0 20px rgba(37, 99, 235, 0.15)',
        'glow-profit': '0 0 20px rgba(0, 230, 118, 0.15)',
        'glow-loss': '0 0 20px rgba(255, 82, 82, 0.15)',
        'glow-sm': '0 0 10px rgba(37, 99, 235, 0.1)',
        card: '0 4px 30px rgba(0, 0, 0, 0.3)',
      },
      animation: {
        'fade-in': 'fadeIn 0.3s ease-out',
        'slide-in-right': 'slideInRight 0.3s ease-out',
        'slide-in-up': 'slideInUp 0.4s ease-out',
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'glow-pulse': 'glowPulse 2s ease-in-out infinite',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        slideInRight: {
          '0%': { transform: 'translateX(100%)', opacity: '0' },
          '100%': { transform: 'translateX(0)', opacity: '1' },
        },
        slideInUp: {
          '0%': { transform: 'translateY(20px)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' },
        },
        glowPulse: {
          '0%, 100%': { boxShadow: '0 0 5px rgba(0, 230, 118, 0.3)' },
          '50%': { boxShadow: '0 0 20px rgba(0, 230, 118, 0.6)' },
        },
      },
    },
  },
  plugins: [],
}
