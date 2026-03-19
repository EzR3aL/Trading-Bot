import { create } from 'zustand'

export type SizeUnit = 'token' | 'usdt'

interface SizeUnitState {
  unit: SizeUnit
  toggle: () => void
}

const stored = localStorage.getItem('sizeUnit') as SizeUnit | null
const initial: SizeUnit = stored === 'usdt' ? 'usdt' : 'token'

export const useSizeUnitStore = create<SizeUnitState>((set, get) => ({
  unit: initial,

  toggle: () => {
    const next = get().unit === 'token' ? 'usdt' : 'token'
    localStorage.setItem('sizeUnit', next)
    set({ unit: next })
  },
}))

/**
 * Format size based on the current unit mode.
 *
 * - token: "13.0600 ETH"
 * - usdt:  "$28.5k" or "$943"
 */
export function formatSize(
  size: number,
  price: number,
  unit: SizeUnit,
  symbol: string,
): string {
  if (size <= 0) return '—'
  if (unit === 'usdt' && price > 0) {
    const usdt = size * price
    if (usdt >= 1_000_000) return `$${(usdt / 1_000_000).toFixed(2)}M`
    if (usdt >= 10_000) return `$${(usdt / 1_000).toFixed(1)}k`
    if (usdt >= 1_000) return `$${(usdt / 1_000).toFixed(2)}k`
    return `$${usdt.toFixed(0)}`
  }
  const base = symbol.replace(/USDT|USDC|USD|PERP/gi, '')
  return `${size.toFixed(4)} ${base}`
}
