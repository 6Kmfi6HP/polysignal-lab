const GAMMA_BASE = 'https://gamma-api.polymarket.com'

export type OfficialSettlementOutcome = 'UP' | 'DOWN'

export type OfficialSettlement = {
  slug: string
  outcome: OfficialSettlementOutcome | null
  label: string | null
  closed: boolean
  resolved: boolean
}

type GammaMarket = {
  closed?: boolean
  outcomes?: unknown
  outcomePrices?: unknown
  umaResolutionStatus?: string | null
}

function parseJsonField<T>(value: unknown): T | null {
  if (Array.isArray(value)) return value as T
  if (typeof value !== 'string' || value.trim() === '') return null
  try {
    return JSON.parse(value) as T
  } catch {
    return null
  }
}

function normalizeOutcome(label: string | null): OfficialSettlementOutcome | null {
  if (!label) return null
  const normalized = label.trim().toLowerCase()
  if (normalized === 'up') return 'UP'
  if (normalized === 'down') return 'DOWN'
  return null
}

/** Strip control chars Gamma occasionally embeds in market JSON. */
export function sanitizeGammaJson(raw: string): string {
  let output = ''
  for (const char of raw) {
    const code = char.charCodeAt(0)
    if (code <= 0x1f && code !== 0x09 && code !== 0x0a && code !== 0x0d) {
      continue
    }
    output += char
  }
  return output
}

export function settlementFromMarket(
  slug: string,
  market: GammaMarket
): OfficialSettlement {
  const outcomes = parseJsonField<string[]>(market.outcomes) ?? []
  const prices = (parseJsonField<Array<string | number>>(market.outcomePrices) ?? [])
    .map((value) => Number(value))
    .map((value) => (Number.isFinite(value) ? value : 0))
  const closed = Boolean(market.closed)
  const resolved =
    market.umaResolutionStatus === 'resolved' ||
    (closed && prices.some((price) => price >= 0.99))

  if (!resolved || outcomes.length === 0 || prices.length === 0) {
    return {
      slug,
      outcome: null,
      label: null,
      closed,
      resolved: false,
    }
  }

  let bestIndex = 0
  for (let index = 1; index < prices.length; index += 1) {
    if ((prices[index] ?? 0) > (prices[bestIndex] ?? 0)) bestIndex = index
  }
  const label = outcomes[bestIndex] ?? null
  return {
    slug,
    outcome: normalizeOutcome(label),
    label,
    closed,
    resolved: true,
  }
}

export async function fetchOfficialSettlement(
  slug: string
): Promise<OfficialSettlement> {
  const response = await fetch(
    `${GAMMA_BASE}/markets/slug/${encodeURIComponent(slug)}`
  )
  if (!response.ok) {
    throw new Error(
      `gamma market ${slug} failed with status ${response.status}`
    )
  }
  const market = JSON.parse(sanitizeGammaJson(await response.text())) as GammaMarket
  return settlementFromMarket(slug, market)
}
