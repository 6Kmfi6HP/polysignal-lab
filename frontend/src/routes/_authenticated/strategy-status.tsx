import { createFileRoute } from '@tanstack/react-router'
import { StrategyStatusPage } from '@/features/strategy-status'

export const Route = createFileRoute('/_authenticated/strategy-status')({
  component: StrategyStatusPage,
})
