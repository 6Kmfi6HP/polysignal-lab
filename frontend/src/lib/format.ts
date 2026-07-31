import { i18n } from '@/context/locale-provider'

const locale = () => i18n.resolvedLanguage ?? 'en'

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return i18n.t('common.unavailable')
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? i18n.t('common.unavailable')
    : new Intl.DateTimeFormat(locale(), {
        dateStyle: 'medium',
        timeStyle: 'short',
      }).format(date)
}

export function formatMoney(value: number, currency = 'USDC'): string {
  if (!Number.isFinite(value))
    return `${i18n.t('common.unavailable')} ${currency}`
  return `${value < 0 ? '-' : value > 0 ? '+' : ''}${new Intl.NumberFormat(locale(), { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(Math.abs(value))} ${currency}`
}

export function formatPercent(value: number, signed = false): string {
  if (!Number.isFinite(value)) return i18n.t('common.unavailable')
  const percent = value * 100
  return `${signed && percent > 0 ? '+' : ''}${new Intl.NumberFormat(locale(), { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(percent)}%`
}

export function formatPrice(value: number): string {
  return Number.isFinite(value)
    ? new Intl.NumberFormat(locale(), {
        minimumFractionDigits: 3,
        maximumFractionDigits: 3,
      }).format(value)
    : i18n.t('common.unavailable')
}

export function formatNumber(value: number, fractionDigits = 2): string {
  return Number.isFinite(value)
    ? new Intl.NumberFormat(locale(), {
        minimumFractionDigits: fractionDigits,
        maximumFractionDigits: fractionDigits,
      }).format(value)
    : i18n.t('common.unavailable')
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds))
    return i18n.t('common.unavailable')
  if (seconds < 60) return formatUnit(Math.round(seconds), 'second', 0)
  if (seconds < 3600) return formatUnit(Math.round(seconds / 60), 'minute', 0)
  return formatUnit(seconds / 3600, 'hour', 1)
}

export function formatFreshness(
  milliseconds: number | null | undefined
): string {
  if (milliseconds == null || !Number.isFinite(milliseconds))
    return i18n.t('common.unavailable')
  return milliseconds < 1000
    ? formatUnit(Math.round(milliseconds), 'millisecond', 0)
    : formatUnit(milliseconds / 1000, 'second', 1)
}

function formatUnit(
  value: number,
  unit: Intl.NumberFormatOptions['unit'],
  fractionDigits: number
) {
  return new Intl.NumberFormat(locale(), {
    style: 'unit',
    unit,
    unitDisplay: 'narrow',
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
  }).format(value)
}

export function humanize(value: string): string {
  return value
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase())
}
