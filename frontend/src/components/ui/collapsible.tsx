/**
 * Input: * as CollapsiblePrimitive from '@radix-ui/react-collapsible', @radix-ui/react-collapsible
 * Output: Collapsible, CollapsibleTrigger, CollapsibleContent
 * Pos: UI Layer - UI components
 *
 * 🔄 Self-reference: When this file changes, update this header
 */









import * as CollapsiblePrimitive from '@radix-ui/react-collapsible'

function Collapsible({
  ...props
}: React.ComponentProps<typeof CollapsiblePrimitive.Root>) {
  return <CollapsiblePrimitive.Root data-slot='collapsible' {...props} />
}

function CollapsibleTrigger({
  ...props
}: React.ComponentProps<typeof CollapsiblePrimitive.CollapsibleTrigger>) {
  return (
    <CollapsiblePrimitive.CollapsibleTrigger
      data-slot='collapsible-trigger'
      {...props}
    />
  )
}

function CollapsibleContent({
  ...props
}: React.ComponentProps<typeof CollapsiblePrimitive.CollapsibleContent>) {
  return (
    <CollapsiblePrimitive.CollapsibleContent
      data-slot='collapsible-content'
      {...props}
    />
  )
}

export { Collapsible, CollapsibleTrigger, CollapsibleContent }
