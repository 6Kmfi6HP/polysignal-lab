/**
 * Input: { createFileRoute } from '@tanstack/react-router', { StrategyStatusPage } from '@/features/strategy-status', @tanstack/react-router, @/features/strategy-status
 * Output: Route
 * Pos: API Layer - Route definitions
 *
 * 🔄 Self-reference: When this file changes, update this header
 */







import { createFileRoute } from '@tanstack/react-router'
import { StrategyStatusPage } from '@/features/strategy-status'

export const Route = createFileRoute('/_authenticated/strategy-status')({
  component: StrategyStatusPage,
})
