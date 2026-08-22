# Radix Primitives and Variant Patterns

## Radix primitive wrapping

Every Radix component follows a consistent wrapping pattern:

1. Import the primitive: `import * as DialogPrimitive from '@radix-ui/react-dialog'`
2. Re-export Root as-is: `const Dialog = DialogPrimitive.Root`
3. Re-export simple parts as-is: `const DialogTrigger = DialogPrimitive.Trigger`
4. Wrap visual parts with forwardRef + custom styles: `DialogOverlay`, `DialogContent`, `DialogTitle`
5. Preserve ref and props spread: `<Primitive ref={ref} {...props} />`

Example structure:

```tsx
import * as DialogPrimitive from '@radix-ui/react-dialog';
import { cn } from '@/lib/utils';

const Dialog = DialogPrimitive.Root;
const DialogTrigger = DialogPrimitive.Trigger;

const DialogContent = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content>
>(({ className, children, ...props }, ref) => (
  <DialogPrimitive.Portal>
    <DialogPrimitive.Content
      ref={ref}
      className={cn('base-classes', className)}
      {...props}
    >
      {children}
    </DialogPrimitive.Content>
  </DialogPrimitive.Portal>
));
```

## Variant-driven API pattern

Components accept `variant` and `size` props, mapped to Record<VariantName, string> style objects:

```tsx
type ButtonVariant = 'primary' | 'secondary' | 'outline' | 'ghost' | 'destructive';
type ButtonSize = 'sm' | 'md' | 'lg' | 'icon';

const variantStyles: Record<ButtonVariant, string> = {
  primary: 'bg-primary text-white hover:bg-primary-600',
  secondary: 'bg-gray-700 text-white hover:bg-gray-800',
  outline: 'border border-gray-300 bg-transparent hover:bg-gray-50',
  ghost: 'bg-transparent hover:bg-gray-100',
  destructive: 'bg-error text-white hover:bg-error-600',
};

const sizeStyles: Record<ButtonSize, string> = {
  sm: 'h-8 px-3 text-sm',
  md: 'h-10 px-4 text-sm',
  lg: 'h-12 px-6 text-base',
  icon: 'h-10 w-10',
};

// In component:
className={cn(
  'base-classes',
  variantStyles[variant],
  sizeStyles[size],
  className
)}
```

## asChild / Slot polymorphism

The `asChild` pattern lets consumers render a component as a different element:

```tsx
import { Slot } from '@radix-ui/react-slot';

interface ButtonProps {
  asChild?: boolean;
  // ... other props
}

const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : 'button';
    return <Comp ref={ref} {...props} />;
  }
);

// Usage:
<Button asChild>
  <a href="/link">Navigate</a>
</Button>
// Renders: <a href="/link" class="button-classes">Navigate</a>
```

Slot merges the Button's props (className, onClick, etc.) into the child `<a>` instead of wrapping it.

## data-state styling

Radix primitives expose state via `data-state="open|closed|active|inactive"` attributes. Style these with Tailwind's data attribute variants:

```tsx
// Switch thumb translates based on checked state
<SwitchPrimitive.Thumb
  className={cn(
    'block h-4 w-4 rounded-full bg-white transition-transform',
    'data-[state=checked]:translate-x-4 data-[state=unchecked]:translate-x-0'
  )}
/>

// Dialog overlay fades in/out
<DialogPrimitive.Overlay
  className={cn(
    'fixed inset-0 bg-black/20',
    'data-[state=open]:animate-in data-[state=closed]:animate-out',
    'data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0'
  )}
/>

// Tabs trigger highlights active tab
<TabsPrimitive.Trigger
  className={cn(
    'px-3 py-1.5 text-gray-600',
    'data-[state=active]:bg-white data-[state=active]:text-gray-900'
  )}
/>
```

## Mobile-responsive Select pattern

Select renders as BottomSheet on mobile, standard Radix Popover on desktop:

```tsx
function Select({ children, value, onValueChange, ...props }) {
  const isMobile = useIsMobile();
  const [sheetOpen, setSheetOpen] = useState(false);

  // Extract options from children for mobile BottomSheet
  const mobileOptions = useMemo(() => {
    // Recursively walk children to find elements with `value` prop
    // Return { value: string, label: ReactNode, disabled?: boolean }[]
  }, [children, isMobile]);

  return (
    <>
      <SelectPrimitive.Root
        value={value}
        onValueChange={onValueChange}
        open={isMobile ? false : open}
        {...props}
      >
        {children}
      </SelectPrimitive.Root>

      {isMobile && (
        <BottomSheet isOpen={sheetOpen} onClose={() => setSheetOpen(false)}>
          {mobileOptions.map((opt) => (
            <button
              key={opt.value}
              onClick={() => {
                onValueChange?.(opt.value);
                setSheetOpen(false);
              }}
              className={cn(
                'w-full flex items-center justify-between px-4 py-3',
                value === opt.value ? 'bg-primary/10 text-primary' : 'text-gray-700'
              )}
            >
              {opt.label}
              {value === opt.value && <Check className="w-4 h-4" />}
            </button>
          ))}
        </BottomSheet>
      )}
    </>
  );
}
```

## Portal pattern for overlays

Dialog, Dropdown, Tooltip Content must render in a Portal to escape z-index stacking:

```tsx
const DialogContent = forwardRef((props, ref) => (
  <DialogPrimitive.Portal>
    <DialogPrimitive.Content ref={ref} {...props} />
  </DialogPrimitive.Portal>
));
```

Portal appends the Content to `document.body` (or a custom container), ensuring it renders above all other content regardless of parent z-index.

## TypeScript forwardRef pattern

All wrapped primitives use `forwardRef` with precise types:

```tsx
const DialogContent = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Content>,  // ref type
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content>  // props type minus ref
>(({ className, children, ...props }, ref) => (
  <DialogPrimitive.Content
    ref={ref}
    className={cn('...', className)}
    {...props}
  >
    {children}
  </DialogPrimitive.Content>
));

DialogContent.displayName = DialogPrimitive.Content.displayName;
```

- `ElementRef<typeof Primitive>`: extracts the ref type from the primitive
- `ComponentPropsWithoutRef<typeof Primitive>`: extracts props without ref
- Always set `displayName` for better React DevTools debugging
