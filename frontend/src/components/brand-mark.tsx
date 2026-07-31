import { type SVGProps } from 'react'

export function BrandMark({ className, ...props }: SVGProps<SVGSVGElement>) {
  return (
    <svg
      viewBox='0 0 24 24'
      fill='none'
      stroke='currentColor'
      strokeWidth='2'
      strokeLinecap='round'
      strokeLinejoin='round'
      aria-hidden='true'
      focusable='false'
      className={className}
      {...props}
    >
      <path d='M3 6h3a4 4 0 0 1 4 4v1' />
      <path d='M3 18h3a4 4 0 0 0 4-4v-1' />
      <rect x='10' y='8' width='4' height='8' rx='1' />
      <path d='M14 12h7' />
    </svg>
  )
}
