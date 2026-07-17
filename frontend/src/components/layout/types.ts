/**
 * Input: { type LinkProps } from '@tanstack/react-router', @tanstack/react-router
 * Output: None
 * Pos: UI Layer - UI components
 *
 * 🔄 Self-reference: When this file changes, update this header
 */









import { type LinkProps } from '@tanstack/react-router'


type BaseNavItem = {
  title: string
  badge?: string
  icon?: React.ElementType
}

type NavLink = BaseNavItem & {
  url: LinkProps['to'] | (string & {})
  items?: never
}

type NavCollapsible = BaseNavItem & {
  items: (BaseNavItem & { url: LinkProps['to'] | (string & {}) })[]
  url?: never
}

type NavItem = NavCollapsible | NavLink

type NavGroup = {
  title: string
  items: NavItem[]
}


export type { NavGroup, NavItem, NavCollapsible, NavLink }
