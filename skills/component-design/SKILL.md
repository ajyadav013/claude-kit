---
name: component-design
description: Design and build UI components following project architecture, component patterns, accessibility standards, and design system rules.
argument-hint: [component name and purpose]
disable-model-invocation: true
---

Design and implement the component: $ARGUMENTS.

## Steps

1. **Read the design system**: Read `docs/references/ui/ui-design-system.md` for visual rules and component standards (if available).

2. **Check existing components**: Check the project's component directory for available UI primitives and established patterns. Search for similar components to follow the project's conventions.

3. **Determine component type**:

   | Type | Location | Naming | Export |
   |------|----------|--------|--------|
   | UI primitive | Project's UI primitives directory | Follow project naming convention | Add to barrel export if applicable |
   | Compound component | Project's UI primitives directory | Follow project naming convention | Add to barrel export if applicable |
   | Feature component | Project's feature directory | Follow project naming convention | Named export |
   | Page sub-component | Same file as page or shared directory | Follow project naming convention | Not exported |

4. **Design the component API**:

   ### Props/Interface Design Checklist
   - Use the project's type system for component interfaces
   - Required props first, optional props after
   - Use the project's composition pattern (children prop, slots, etc.)
   - Support style extension (className, style, css prop, etc.)
   - Event handlers: consistent naming convention (`on<Event>`, `handle<Event>`, etc.)
   - Use discriminated unions or enums for variant props
   - No boolean prop overload — use string union types or enums for variants

   ### Example (TypeScript/React-style)
   ```tsx
   interface MetricCardProps {
     title: string;
     value: string | number;
     trend?: { direction: 'up' | 'down' | 'flat'; percentage: number };
     status?: 'green' | 'amber' | 'red';
     className?: string;
     onClick?: () => void;
   }
   ```

   ### Example (Template-based framework style)
   ```vue
   interface Props {
     title: string
     value: string | number
     trend?: { direction: 'up' | 'down' | 'flat'; percentage: number }
     status?: 'green' | 'amber' | 'red'
   }
   ```

5. **Implement following these rules**:

   ### Structure
   - Follow the project's import ordering conventions
   - Type definitions near the top
   - Hooks/lifecycle methods in consistent order
   - Derived values and computed properties
   - Event handlers
   - Early returns for loading, empty, and error states
   - Main render/template

   ### Compound Component Pattern
   When building a compound component (e.g., `Card`, `DetailPanel`):
   - Parent component provides shared context
   - Sub-components consume context or accept explicit props
   - Usage: compose sub-components within parent wrapper
   
   Example:
   ```
   <Card>
     <CardHeader>Title</CardHeader>
     <CardContent>Body</CardContent>
   </Card>
   ```

   ### Accessibility Requirements
   - All interactive elements are keyboard-accessible
   - Icon-only buttons have accessible labels (aria-label, title, etc.)
   - Form inputs have associated labels
   - Use semantic HTML or equivalent (`nav`, `main`, `section`, `article`, `button`, etc.)
   - Focus management: visible focus indicators
   - Use the project's UI library for complex interactions (dialogs, selects, dropdowns, tabs)

6. **Register the component**: If it's a UI primitive or compound component, add it to the project's barrel export or component registry.

7. **Verify**: Run the project's linter, type checker, and build to confirm all checks pass.

## References

- UI primitives: Project's UI primitives directory/barrel export
- Design system: `docs/references/ui/ui-design-system.md` (if available)
- UX patterns: `docs/references/ui/ux-patterns.md` (if available)
- Rules: `.claude/rules/frontend-best-practices.md`, `.claude/rules/responsive-and-accessibility.md`

## Examples

The following examples use React/TypeScript syntax, but the principles apply to any component-based framework. Adapt patterns to your project's stack (Vue, Svelte, Angular, etc.).

### Simple presentational component
```tsx
import { cn } from '@/lib/utils';
import { Badge } from '@/components/ui';

interface StatusIndicatorProps {
  status: 'green' | 'amber' | 'red';
  label: string;
  className?: string;
}

export function StatusIndicator({ status, label, className }: StatusIndicatorProps) {
  return (
    <div className={cn('flex items-center gap-2', className)}>
      <span className={cn('w-2 h-2 rounded-full', {
        'bg-green-500': status === 'green',
        'bg-amber-500': status === 'amber',
        'bg-red-500': status === 'red',
      })} />
      <Badge variant={status === 'red' ? 'destructive' : status === 'amber' ? 'warning' : 'success'}>
        {label}
      </Badge>
    </div>
  );
}
```

### Interactive component with UI library
```tsx
import * as Dialog from '@radix-ui/react-dialog';
import { Button } from '@/components/ui';
import { X } from 'lucide-react';

interface ConfirmDialogProps {
  title: string;
  description: string;
  onConfirm: () => void;
  trigger: React.ReactNode;
}

export function ConfirmDialog({ title, description, onConfirm, trigger }: ConfirmDialogProps) {
  return (
    <Dialog.Root>
      <Dialog.Trigger asChild>{trigger}</Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/40" />
        <Dialog.Content className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 bg-white rounded-lg p-4 w-full max-w-md">
          <Dialog.Title className="text-sm font-semibold text-gray-900">{title}</Dialog.Title>
          <Dialog.Description className="text-sm text-gray-500 mt-2">{description}</Dialog.Description>
          <div className="flex justify-end gap-3 mt-4">
            <Dialog.Close asChild>
              <Button variant="ghost" size="sm">Cancel</Button>
            </Dialog.Close>
            <Button size="sm" onClick={onConfirm}>Confirm</Button>
          </div>
          <Dialog.Close asChild>
            <button className="absolute top-3 right-3" aria-label="Close">
              <X className="w-4 h-4 text-gray-400" />
            </button>
          </Dialog.Close>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
```
