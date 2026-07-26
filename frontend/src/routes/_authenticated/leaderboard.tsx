import { createFileRoute } from '@tanstack/react-router'
import { LeaderboardPage } from '@/features/leaderboard'

export const Route = createFileRoute('/_authenticated/leaderboard')({
  component: LeaderboardPage,
})
