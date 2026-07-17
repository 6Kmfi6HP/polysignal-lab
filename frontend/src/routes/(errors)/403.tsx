/**
 * Input: { createFileRoute } from '@tanstack/react-router', { ForbiddenError } from '@/features/errors/forbidden', @tanstack/react-router, @/features/errors/forbidden
 * Output: Route
 * Pos: API Layer - Route definitions
 *
 * 🔄 Self-reference: When this file changes, update this header
 */









import { createFileRoute } from '@tanstack/react-router'
import { ForbiddenError } from '@/features/errors/forbidden'

export const Route = createFileRoute('/(errors)/403')({
  component: ForbiddenError,
})
