import { afterEach, describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { i18n } from '@/context/locale-provider'
import { DetailList } from './dashboard'

describe('DetailList', () => {
  afterEach(async () => {
    await i18n.changeLanguage('en')
  })

  it('translates trade detail field labels and nested values in Chinese', async () => {
    await i18n.changeLanguage('zh-CN')
    render(
      <DetailList
        values={{
          asset: 'SOL',
          closed_at: '2026-08-02T22:42:59.558681+00:00',
          exit_mode: 'TAKE_PROFIT',
          details: {
            entry_fee: 0,
            exit_reason: 'TAKE_PROFIT',
            fee_model: 'ignored_v1',
          },
        }}
      />
    )

    expect(screen.getByText('资产')).toBeInTheDocument()
    expect(screen.getByText('平仓时间')).toBeInTheDocument()
    expect(screen.getByText('平仓方式')).toBeInTheDocument()
    expect(screen.getAllByText('止盈').length).toBeGreaterThanOrEqual(2)
    expect(screen.getByText('入场手续费')).toBeInTheDocument()
    expect(screen.getByText('平仓原因')).toBeInTheDocument()
    expect(screen.getByText('手续费模型')).toBeInTheDocument()
    expect(screen.queryByText('Closed At')).not.toBeInTheDocument()
    expect(screen.queryByText('TAKE_PROFIT')).not.toBeInTheDocument()
  })
})
