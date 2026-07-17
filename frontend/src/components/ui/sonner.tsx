/**
 * Input: { Toaster as Sonner, ToasterProps } from 'sonner', { useTheme } from '@/context/theme-provider', sonner, @/context/theme-provider
 * Output: Toaster
 * Pos: UI Layer - UI components
 *
 * 🔄 Self-reference: When this file changes, update this header
 */









import { Toaster as Sonner, ToasterProps } from 'sonner'
import { useTheme } from '@/context/theme-provider'

export function Toaster({ ...props }: ToasterProps) {
  const { theme = 'system' } = useTheme()

  return (
    <Sonner
      theme={theme as ToasterProps['theme']}
      className='toaster group [&_div[data-content]]:w-full'
      style={
        {
          '--normal-bg': 'var(--popover)',
          '--normal-text': 'var(--popover-foreground)',
          '--normal-border': 'var(--border)',
        } as React.CSSProperties
      }
      {...props}
    />
  )
}
