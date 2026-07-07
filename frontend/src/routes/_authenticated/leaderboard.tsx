/**
 * Input: { createFileRoute } from '@tanstack/react-router', { LeaderboardPage } from '@/features/leaderboard', @tanstack/react-router, @/features/leaderboard
 * Output: Route
 * Pos: API Layer - Route definitions
 *
 * 🔄 Self-reference: When this file changes, update this header
 */







import { createFileRoute } from '@tanstack/react-router'
import { LeaderboardPage } from '@/features/leaderboard'

export const Route = createFileRoute('/_authenticated/leaderboard')({
  component: LeaderboardPage,
})
