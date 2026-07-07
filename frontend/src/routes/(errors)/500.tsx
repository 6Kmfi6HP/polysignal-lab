/**
 * Input: { createFileRoute } from '@tanstack/react-router', { GeneralError } from '@/features/errors/general-error', @tanstack/react-router, @/features/errors/general-error
 * Output: Route
 * Pos: API Layer - Route definitions
 *
 * 🔄 Self-reference: When this file changes, update this header
 */





import { createFileRoute } from '@tanstack/react-router'
import { GeneralError } from '@/features/errors/general-error'

export const Route = createFileRoute('/(errors)/500')({
  component: GeneralError,
})
