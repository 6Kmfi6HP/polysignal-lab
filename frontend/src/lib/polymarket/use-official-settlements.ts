import { useMemo } from 'react'
import { useQueries } from '@tanstack/react-query'
import {
  fetchOfficialSettlement,
  type OfficialSettlement,
} from '@/lib/polymarket/gamma'

export function useOfficialSettlements(slugs: string[]) {
  const slugKey = slugs.join('\0')
  const uniqueSlugs = useMemo(() => {
    const seen = new Set<string>()
    const ordered: string[] = []
    for (const slug of slugKey.split('\0')) {
      const trimmed = slug.trim()
      if (!trimmed || seen.has(trimmed)) continue
      seen.add(trimmed)
      ordered.push(trimmed)
    }
    return ordered
  }, [slugKey])

  return useQueries({
    queries: uniqueSlugs.map((slug) => ({
      queryKey: ['polymarket-settlement', slug] as const,
      queryFn: () => fetchOfficialSettlement(slug),
      staleTime: 60_000,
      gcTime: 30 * 60_000,
      retry: 1,
      refetchOnWindowFocus: false,
    })),
    combine: (results) => {
      const bySlug = new Map<string, OfficialSettlement>()
      const pending = new Set<string>()
      const failed = new Set<string>()
      results.forEach((result, index) => {
        const slug = uniqueSlugs[index]
        if (!slug) return
        if (result.data) bySlug.set(slug, result.data)
        if (result.isPending) pending.add(slug)
        if (result.isError) failed.add(slug)
      })
      return {
        bySlug,
        pending,
        failed,
        isLoading: results.some((result) => result.isPending),
      }
    },
  })
}
