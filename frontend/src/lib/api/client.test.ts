import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, getOverview } from './client'

describe('getOverview', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('returns the parsed JSON payload on success', async () => {
    const payload = {
      counts: { signals: 1 },
      latest_report: null,
      calibration_breakdown: {},
      strategy_status: [],
    }
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => payload,
      })
    )

    const result = await getOverview()

    expect(result).toEqual(payload)
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/api/overview'))
  })

  it('throws ApiError when the response is not ok', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: false, status: 500, json: async () => ({}) })
    )

    await expect(getOverview()).rejects.toBeInstanceOf(ApiError)
  })
})
