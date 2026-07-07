/**
 * Input: { createFileRoute } from '@tanstack/react-router', { UnauthorisedError } from '@/features/errors/unauthorized-error', @tanstack/react-router, @/features/errors/unauthorized-error
 * Output: Route
 * Pos: API Layer - Route definitions
 *
 * 🔄 Self-reference: When this file changes, update this header
 */







import { createFileRoute } from '@tanstack/react-router'
import { UnauthorisedError } from '@/features/errors/unauthorized-error'

export const Route = createFileRoute('/(errors)/401')({
  component: UnauthorisedError,
})
