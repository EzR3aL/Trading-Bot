import api from './client'

export interface ValidateSourceResponse {
  valid: boolean
  wallet_label: string
  trades_30d: number
  available: string[]
  unavailable: string[]
  warning: string | null
}

export interface LeverageLimitsResponse {
  exchange: string
  symbol: string
  max_leverage: number
}

export async function validateSourceWallet(
  wallet: string,
  target_exchange: string,
): Promise<ValidateSourceResponse> {
  const r = await api.post('/copy-trading/validate-source', {
    wallet,
    target_exchange,
  })
  return r.data
}

export async function getLeverageLimits(
  exchange: string,
  symbol: string,
): Promise<LeverageLimitsResponse> {
  const r = await api.get(`/exchanges/${exchange}/leverage-limits`, {
    params: { symbol },
  })
  return r.data
}
