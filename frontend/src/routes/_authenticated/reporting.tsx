import { createFileRoute } from '@tanstack/react-router'
import { ReportingPage } from '@/features/reporting'

export const Route = createFileRoute('/_authenticated/reporting')({
  component: ReportingPage,
})
