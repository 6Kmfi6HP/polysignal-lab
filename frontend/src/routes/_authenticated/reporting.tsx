/**
 * Input: { createFileRoute } from '@tanstack/react-router', { ReportingPage } from '@/features/reporting', @tanstack/react-router, @/features/reporting
 * Output: Route
 * Pos: API Layer - Route definitions
 *
 * 🔄 Self-reference: When this file changes, update this header
 */







import { createFileRoute } from '@tanstack/react-router'
import { ReportingPage } from '@/features/reporting'

export const Route = createFileRoute('/_authenticated/reporting')({
  component: ReportingPage,
})
