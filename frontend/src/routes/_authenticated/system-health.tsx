import { createFileRoute } from '@tanstack/react-router'
import { SystemHealthPage } from '@/features/system-health'

export const Route = createFileRoute('/_authenticated/system-health')({
  component: SystemHealthPage,
})
