/**
 * Input: { createFileRoute } from '@tanstack/react-router', { AuthenticatedLayout } from '@/components/layout/authenticated-layout', @tanstack/react-router, @/components/layout/authenticated-layout
 * Output: Route
 * Pos: API Layer - Route definitions
 *
 * 🔄 Self-reference: When this file changes, update this header
 */





import { createFileRoute } from '@tanstack/react-router'
import { AuthenticatedLayout } from '@/components/layout/authenticated-layout'

export const Route = createFileRoute('/_authenticated')({
  component: AuthenticatedLayout,
})
