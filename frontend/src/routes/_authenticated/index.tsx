/**
 * Input: { createFileRoute } from '@tanstack/react-router', { OverviewPage } from '@/features/overview', @tanstack/react-router, @/features/overview
 * Output: Route
 * Pos: API Layer - Route definitions
 *
 * 🔄 Self-reference: When this file changes, update this header
 */





import { createFileRoute } from '@tanstack/react-router'
import { OverviewPage } from '@/features/overview'

export const Route = createFileRoute('/_authenticated/')({
  component: OverviewPage,
})
