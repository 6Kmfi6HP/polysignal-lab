/**
 * Input: { createFileRoute } from '@tanstack/react-router', { SignalsPage } from '@/features/signals', @tanstack/react-router, @/features/signals
 * Output: Route
 * Pos: API Layer - Route definitions
 *
 * 🔄 Self-reference: When this file changes, update this header
 */







import { createFileRoute } from '@tanstack/react-router'
import { SignalsPage } from '@/features/signals'

export const Route = createFileRoute('/_authenticated/signals')({
  component: SignalsPage,
})
