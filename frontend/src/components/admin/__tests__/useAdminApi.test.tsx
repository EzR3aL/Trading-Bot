import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'

const mockGet = vi.fn()
const mockPut = vi.fn()
const mockPost = vi.fn()
const mockDelete = vi.fn()

vi.mock('../../../api/client', () => ({
  default: {
    get: (...args: unknown[]) => mockGet(...args),
    put: (...args: unknown[]) => mockPut(...args),
    post: (...args: unknown[]) => mockPost(...args),
    delete: (...args: unknown[]) => mockDelete(...args),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  },
  setTokenExpiry: vi.fn(),
  clearTokenExpiry: vi.fn(),
}))

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: string) => fallback || key,
  }),
}))

vi.mock('../../../utils/api-error', () => ({
  getApiErrorMessage: (_err: unknown, fallback: string) => fallback,
}))

vi.mock('../../../stores/toastStore', () => ({
  useToastStore: {
    getState: () => ({ addToast: vi.fn() }),
  },
}))

import { useAdminApi } from '../useAdminApi'

describe('useAdminApi', () => {
  beforeEach(() => {
    mockGet.mockReset()
    mockPut.mockReset()
    mockPost.mockReset()
    mockDelete.mockReset()
  })

  it('exposes the documented set of fields and handlers', () => {
    const showMessage = vi.fn()
    const { result } = renderHook(() => useAdminApi(showMessage))

    // Connections
    expect(result.current.connStatus).toBeNull()
    expect(result.current.connLoading).toBe(false)
    expect(typeof result.current.loadConnectionStatus).toBe('function')

    // Hyperliquid
    expect(result.current.hlRevenue).toBeNull()
    expect(typeof result.current.loadHlRevenue).toBe('function')
    expect(result.current.hlAdminForm).toEqual({ builder_address: '', builder_fee: 10, referral_code: '' })
    expect(typeof result.current.saveHlAdminSettings).toBe('function')

    // Affiliate
    expect(result.current.saving).toBe(false)
    expect(result.current.affiliateLinks).toEqual({})
    expect(typeof result.current.loadAffiliateLinks).toBe('function')
    expect(typeof result.current.saveAffiliateLink).toBe('function')
    expect(typeof result.current.deleteAffiliateLink).toBe('function')

    // Admin UIDs
    expect(result.current.adminUidPage).toBe(1)
    expect(result.current.adminUidStats).toEqual({ total: 0, verified: 0, pending: 0 })
    expect(typeof result.current.loadAdminUids).toBe('function')
    expect(typeof result.current.verifyAdminUid).toBe('function')
  })

  it('loadConnectionStatus updates connStatus on success', async () => {
    const showMessage = vi.fn()
    const payload = { services: {}, circuit_breakers: {} }
    mockGet.mockResolvedValueOnce({ data: payload })

    const { result } = renderHook(() => useAdminApi(showMessage))
    await act(async () => {
      await result.current.loadConnectionStatus()
    })

    expect(mockGet).toHaveBeenCalledWith('/config/connections')
    expect(result.current.connStatus).toEqual(payload)
    expect(result.current.connLoading).toBe(false)
  })

  it('loadConnectionStatus calls showMessage on error', async () => {
    const showMessage = vi.fn()
    mockGet.mockRejectedValueOnce(new Error('boom'))

    const { result } = renderHook(() => useAdminApi(showMessage))
    await act(async () => {
      await result.current.loadConnectionStatus()
    })

    expect(showMessage).toHaveBeenCalled()
    expect(result.current.connStatus).toBeNull()
  })

  it('loadAffiliateLinks builds forms map from API response', async () => {
    const showMessage = vi.fn()
    mockGet.mockResolvedValueOnce({
      data: [
        { exchange_type: 'bitget', affiliate_url: 'https://b', label: 'B', is_active: true, uid_required: true },
      ],
    })

    const { result } = renderHook(() => useAdminApi(showMessage))
    await act(async () => {
      await result.current.loadAffiliateLinks()
    })

    expect(mockGet).toHaveBeenCalledWith('/affiliate-links')
    expect(result.current.affiliateLinks.bitget).toEqual({
      affiliate_url: 'https://b',
      label: 'B',
      is_active: true,
    })
    expect(result.current.affiliateForms.bitget).toEqual({ url: 'https://b', label: 'B', active: true, uidRequired: true })
    expect(result.current.affiliateLoaded).toBe(true)
  })

  it('saveAffiliateLink skips PUT when form.url is empty', async () => {
    const showMessage = vi.fn()
    const { result } = renderHook(() => useAdminApi(showMessage))

    await act(async () => {
      await result.current.saveAffiliateLink('bitget')
    })

    expect(mockPut).not.toHaveBeenCalled()
  })

  it('verifyAdminUid PUTs the verify endpoint and refreshes the list', async () => {
    const showMessage = vi.fn()
    mockPut.mockResolvedValueOnce({})
    mockGet.mockResolvedValueOnce({
      data: { items: [], total: 0, pages: 1, page: 1, stats: { total: 0, verified: 0, pending: 0 } },
    })

    const { result } = renderHook(() => useAdminApi(showMessage))
    await act(async () => {
      await result.current.verifyAdminUid(42, true)
    })

    expect(mockPut).toHaveBeenCalledWith('/config/admin/affiliate-uids/42/verify', { verified: true })
    await waitFor(() => expect(mockGet).toHaveBeenCalledWith(
      '/config/admin/affiliate-uids',
      expect.objectContaining({ params: expect.any(Object) }),
    ))
  })
})
