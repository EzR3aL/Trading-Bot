/**
 * Shared types and constants for the Admin page sub-components.
 * Extracted from pages/Admin.tsx as part of the page-decomposition refactor.
 */

export type TabKey = 'users' | 'broadcasts' | 'revenue' | 'connections' | 'affiliateLinks' | 'hyperliquid'

export interface AdminTabDef {
  key: TabKey
  labelKey: string
}

export const TABS: readonly AdminTabDef[] = [
  { key: 'users', labelKey: 'admin.users' },
  { key: 'broadcasts', labelKey: 'broadcast.title' },
  { key: 'revenue', labelKey: 'admin.revenue' },
  { key: 'connections', labelKey: 'settings.connections' },
  { key: 'affiliateLinks', labelKey: 'settings.affiliateLinks' },
  { key: 'hyperliquid', labelKey: 'settings.hyperliquid' },
] as const

export const AFFILIATE_EXCHANGES = ['bitget', 'weex', 'hyperliquid', 'bitunix', 'bingx'] as const

export interface AffiliateLinkSummary {
  affiliate_url: string
  label: string
  is_active: boolean
}

export interface AffiliateForm {
  url: string
  label: string
  active: boolean
  uidRequired: boolean
}

export interface HlAdminSettings {
  builder_address: string
  builder_fee: number
  referral_code: string
  sources: Record<string, string>
}

export interface HlAdminForm {
  builder_address: string
  builder_fee: number
  referral_code: string
}

export interface AdminUidStats {
  total: number
  verified: number
  pending: number
}

export type AdminUidFilter = 'all' | 'pending' | 'verified'
