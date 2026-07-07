/**
 * Input: { createFileRoute } from '@tanstack/react-router', { SystemHealthPage } from '@/features/system-health', @tanstack/react-router, @/features/system-health
 * Output: Route
 * Pos: API Layer - Route definitions
 *
 * 🔄 Self-reference: When this file changes, update this header
 */





import { createFileRoute } from '@tanstack/react-router'
import { SystemHealthPage } from '@/features/system-health'

export const Route = createFileRoute('/_authenticated/system-health')({
  component: SystemHealthPage,
})
