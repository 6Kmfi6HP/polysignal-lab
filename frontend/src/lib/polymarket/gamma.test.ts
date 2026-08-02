import { describe, expect, it } from 'vitest'
import {
  sanitizeGammaJson,
  settlementFromMarket,
} from './gamma'

describe('settlementFromMarket', () => {
  it('picks Down when closed market resolves to ["0","1"]', () => {
    expect(
      settlementFromMarket('btc-updown-5m-1', {
        closed: true,
        umaResolutionStatus: 'resolved',
        outcomes: '["Up", "Down"]',
        outcomePrices: '["0", "1"]',
      })
    ).toEqual({
      slug: 'btc-updown-5m-1',
      outcome: 'DOWN',
      label: 'Down',
      closed: true,
      resolved: true,
    })
  })

  it('picks Up when closed market resolves to ["1","0"]', () => {
    expect(
      settlementFromMarket('eth-updown-5m-2', {
        closed: true,
        umaResolutionStatus: 'resolved',
        outcomes: ['Up', 'Down'],
        outcomePrices: ['1', '0'],
      }).outcome
    ).toBe('UP')
  })

  it('marks open markets as unresolved even with mid prices', () => {
    expect(
      settlementFromMarket('sol-updown-5m-3', {
        closed: false,
        umaResolutionStatus: null,
        outcomes: '["Up", "Down"]',
        outcomePrices: '["0.2", "0.8"]',
      })
    ).toMatchObject({
      resolved: false,
      outcome: null,
      closed: false,
    })
  })

  it('treats closed markets with a near-1 price as resolved without uma status', () => {
    expect(
      settlementFromMarket('xrp-updown-5m-4', {
        closed: true,
        outcomes: '["Up", "Down"]',
        outcomePrices: '["0.01", "0.99"]',
      }).outcome
    ).toBe('DOWN')
  })
})

describe('sanitizeGammaJson', () => {
  it('strips embedded control characters so JSON.parse succeeds', () => {
    const dirty = '{"slug":"btc","outcomes":["Up"\u0001,"Down"]}'
    expect(JSON.parse(sanitizeGammaJson(dirty))).toEqual({
      slug: 'btc',
      outcomes: ['Up', 'Down'],
    })
  })
})
