import { describe, expect, it } from 'vitest'
import {
  formatDateTime,
  formatDuration,
  formatFreshness,
  formatMoney,
  formatPercent,
  formatPrice,
  humanize,
} from './format'

describe('dashboard formatters', () => {
  it('formats signed financial values without hiding losses', () => {
    expect(formatMoney(4)).toBe('+4.00 USDC')
    expect(formatMoney(-1.25)).toBe('-1.25 USDC')
    expect(formatPercent(0.125, true)).toBe('+12.5%')
    expect(formatPercent(-0.125, true)).toBe('-12.5%')
  })

  it('handles missing and invalid telemetry values', () => {
    expect(formatDateTime(null)).toBe('Unavailable')
    expect(formatDateTime('not-a-date')).toBe('Unavailable')
    expect(formatDuration(null)).toBe('Unavailable')
    expect(formatFreshness(Number.NaN)).toBe('Unavailable')
    expect(formatPrice(Number.POSITIVE_INFINITY)).toBe('Unavailable')
  })

  it('uses compact operational units and readable labels', () => {
    expect(formatDuration(90)).toBe('2m')
    expect(formatFreshness(1250)).toBe('1.3s')
    expect(humanize('unsupported_market')).toBe('Unsupported Market')
  })
})
