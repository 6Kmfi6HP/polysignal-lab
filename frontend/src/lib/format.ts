const dateTimeFormatter = new Intl.DateTimeFormat('en', {
  dateStyle: 'medium',
  timeStyle: 'short',
})

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return 'Unavailable'
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? 'Unavailable'
    : dateTimeFormatter.format(date)
}

export function formatMoney(value: number, currency = 'USDC'): string {
  if (!Number.isFinite(value)) return `Unavailable ${currency}`
  return `${value < 0 ? '-' : value > 0 ? '+' : ''}${Math.abs(value).toFixed(2)} ${currency}`
}

export function formatPercent(value: number, signed = false): string {
  if (!Number.isFinite(value)) return 'Unavailable'
  const percent = value * 100
  return `${signed && percent > 0 ? '+' : ''}${percent.toFixed(1)}%`
}

export function formatPrice(value: number): string {
  return Number.isFinite(value) ? value.toFixed(3) : 'Unavailable'
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return 'Unavailable'
  if (seconds < 60) return `${Math.round(seconds)}s`
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`
  return `${(seconds / 3600).toFixed(1)}h`
}

export function formatFreshness(
  milliseconds: number | null | undefined
): string {
  if (milliseconds == null || !Number.isFinite(milliseconds))
    return 'Unavailable'
  return milliseconds < 1000
    ? `${Math.round(milliseconds)}ms`
    : `${(milliseconds / 1000).toFixed(1)}s`
}

export function humanize(value: string): string {
  return value
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase())
}
