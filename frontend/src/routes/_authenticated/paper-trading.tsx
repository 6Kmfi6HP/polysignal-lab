import { createFileRoute } from '@tanstack/react-router'
import { PaperTradingPage } from '@/features/paper-trading'

export const Route = createFileRoute('/_authenticated/paper-trading')({
  component: PaperTradingPage,
})
