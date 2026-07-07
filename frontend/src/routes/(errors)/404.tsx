/**
 * Input: { createFileRoute } from '@tanstack/react-router', { NotFoundError } from '@/features/errors/not-found-error', @tanstack/react-router, @/features/errors/not-found-error
 * Output: Route
 * Pos: API Layer - Route definitions
 *
 * 🔄 Self-reference: When this file changes, update this header
 */







import { createFileRoute } from '@tanstack/react-router'
import { NotFoundError } from '@/features/errors/not-found-error'

export const Route = createFileRoute('/(errors)/404')({
  component: NotFoundError,
})
