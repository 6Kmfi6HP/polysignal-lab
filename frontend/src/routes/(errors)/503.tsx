/**
 * Input: { createFileRoute } from '@tanstack/react-router', { MaintenanceError } from '@/features/errors/maintenance-error', @tanstack/react-router, @/features/errors/maintenance-error
 * Output: Route
 * Pos: API Layer - Route definitions
 *
 * 🔄 Self-reference: When this file changes, update this header
 */









import { createFileRoute } from '@tanstack/react-router'
import { MaintenanceError } from '@/features/errors/maintenance-error'

export const Route = createFileRoute('/(errors)/503')({
  component: MaintenanceError,
})
