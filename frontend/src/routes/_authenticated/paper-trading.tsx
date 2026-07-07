/**
 * Input: { createFileRoute } from '@tanstack/react-router', { PaperTradingPage } from '@/features/paper-trading', @tanstack/react-router, @/features/paper-trading
 * Output: Route
 * Pos: API Layer - Route definitions
 *
 * 🔄 Self-reference: When this file changes, update this header
 */







import { createFileRoute } from '@tanstack/react-router'
import { PaperTradingPage } from '@/features/paper-trading'

export const Route = createFileRoute('/_authenticated/paper-trading')({
  component: PaperTradingPage,
})
