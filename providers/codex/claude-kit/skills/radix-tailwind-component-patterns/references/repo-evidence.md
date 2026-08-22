# Repo Evidence

Genericized snippets from production services. All internal service names, repos, paths, and company-specific branding removed.

## File structure

```
src/
├── components/
│   ├── ui/
│   │   ├── Button.tsx
│   │   ├── Dialog.tsx
│   │   ├── Select.tsx
│   │   ├── Switch.tsx
│   │   ├── Tabs.tsx
│   │   ├── Toast.tsx
│   │   ├── Tooltip.tsx
│   │   ├── DropdownMenu.tsx
│   │   └── index.ts
│   └── (feature components)
├── lib/
│   └── utils.ts
└── index.css
```

## cn() utility (lib/utils.ts)

```ts
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

/**
 * Merge class names with Tailwind CSS support
 * Combines clsx for conditional classes and tailwind-merge for deduplication
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
```

## Tailwind v4 @theme tokens (index.css)

```css
@import "tailwindcss";
@plugin "@tailwindcss/typography";

@custom-variant pointer-fine (@media (pointer: fine));
@custom-variant pointer-coarse (@media (pointer: coarse));

@theme {
  /* Breakpoints */
  --breakpoint-xs: 430px;

  /* Primary colors */
  --color-primary-50: #eef2ff;
  --color-primary-100: #e0e7ff;
  --color-primary-500: #6366f1;
  --color-primary-600: #4f46e5;
  --color-primary: #6366f1;

  /* Semantic colors */
  --color-success: #10B981;
  --color-warning: #F59E0B;
  --color-error: #EF4444;

  /* Border radius */
  --radius-sm: 0.25rem;
  --radius-md: 0.375rem;
  --radius-lg: 0.5rem;
  --radius-full: 9999px;

  /* Font families */
  --font-sans: Inter, system-ui, sans-serif;
}

@layer utilities {
  .scrollbar-hide {
    -ms-overflow-style: none;
    scrollbar-width: none;
  }
  .scrollbar-hide::-webkit-scrollbar {
    display: none;
  }

  .pb-safe {
    padding-bottom: env(safe-area-inset-bottom, 0px);
  }
}

@keyframes slideIn {
  from { transform: translateX(100%); opacity: 0; }
  to { transform: translateX(0); opacity: 1; }
}

.animate-slideIn {
  animation: slideIn 0.3s ease-out;
}

@media (prefers-reduced-motion: reduce) {
  .animate-slideIn {
    animation: none;
  }
  *::before,
  *::after {
    transition-duration: 0.01ms !important;
  }
}
```

## Button with variants (components/ui/Button.tsx)

```tsx
import { forwardRef, type ButtonHTMLAttributes } from 'react';
import { Slot } from '@radix-ui/react-slot';
import { cn } from '@/lib/utils';

type ButtonVariant = 'primary' | 'secondary' | 'outline' | 'ghost' | 'destructive';
type ButtonSize = 'sm' | 'md' | 'lg' | 'icon';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  asChild?: boolean;
  isLoading?: boolean;
}

const variantStyles: Record<ButtonVariant, string> = {
  primary: 'bg-primary text-white hover:bg-primary-600 focus:ring-primary/20',
  secondary: 'bg-gray-700 text-white hover:bg-gray-800',
  outline: 'border border-gray-300 bg-transparent hover:bg-gray-50',
  ghost: 'bg-transparent hover:bg-gray-100',
  destructive: 'bg-error text-white hover:bg-error-600 focus:ring-error/20',
};

const sizeStyles: Record<ButtonSize, string> = {
  sm: 'h-8 px-3 text-sm',
  md: 'h-10 px-4 text-sm',
  lg: 'h-12 px-6 text-base',
  icon: 'h-10 w-10',
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = 'primary', size = 'md', asChild = false, isLoading = false, disabled, children, ...props }, ref) => {
    const Comp = asChild ? Slot : 'button';

    return (
      <Comp
        className={cn(
          'inline-flex items-center justify-center rounded-lg font-medium transition-colors',
          'focus:outline-none focus:ring-4 disabled:opacity-50 disabled:cursor-not-allowed',
          variantStyles[variant],
          sizeStyles[size],
          className
        )}
        ref={ref}
        disabled={disabled ?? isLoading}
        {...props}
      >
        {isLoading ? <LoadingSpinner /> : children}
      </Comp>
    );
  }
);
```

## Dialog (components/ui/Dialog.tsx)

```tsx
import * as DialogPrimitive from '@radix-ui/react-dialog';
import { X } from 'lucide-react';
import { cn } from '@/lib/utils';

const Dialog = DialogPrimitive.Root;
const DialogTrigger = DialogPrimitive.Trigger;

const DialogOverlay = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Overlay>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Overlay>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Overlay
    ref={ref}
    className={cn(
      'fixed inset-0 z-50 bg-black/20',
      'data-[state=open]:animate-in data-[state=closed]:animate-out',
      'data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0',
      className
    )}
    {...props}
  />
));

const DialogContent = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content>
>(({ className, children, ...props }, ref) => (
  <DialogPrimitive.Portal>
    <DialogOverlay />
    <DialogPrimitive.Content
      ref={ref}
      className={cn(
        'fixed left-[50%] top-[50%] z-50 w-full max-w-lg translate-x-[-50%] translate-y-[-50%]',
        'bg-white p-6 shadow-lg rounded-lg',
        'data-[state=open]:animate-in data-[state=closed]:animate-out',
        'data-[state=open]:zoom-in-95 data-[state=closed]:zoom-out-95',
        className
      )}
      {...props}
    >
      {children}
      <DialogPrimitive.Close className="absolute right-4 top-4 opacity-70 hover:opacity-100">
        <X className="h-4 w-4" />
      </DialogPrimitive.Close>
    </DialogPrimitive.Content>
  </DialogPrimitive.Portal>
));
```

## Switch (components/ui/Switch.tsx)

```tsx
import * as SwitchPrimitive from '@radix-ui/react-switch';
import { cn } from '@/lib/utils';

const Switch = React.forwardRef<
  React.ElementRef<typeof SwitchPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof SwitchPrimitive.Root>
>(({ className, ...props }, ref) => (
  <SwitchPrimitive.Root
    ref={ref}
    className={cn(
      'peer inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full',
      'border-2 border-transparent transition-colors duration-200',
      'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary',
      'disabled:cursor-not-allowed disabled:opacity-50',
      'data-[state=checked]:bg-primary data-[state=unchecked]:bg-gray-200',
      className
    )}
    {...props}
  >
    <SwitchPrimitive.Thumb
      className={cn(
        'block h-4 w-4 rounded-full bg-white shadow-sm',
        'transition-transform duration-200',
        'data-[state=checked]:translate-x-4 data-[state=unchecked]:translate-x-0'
      )}
    />
  </SwitchPrimitive.Root>
));
```

## Tabs with variants (components/ui/Tabs.tsx)

```tsx
import * as TabsPrimitive from '@radix-ui/react-tabs';
import { cn } from '@/lib/utils';

const Tabs = TabsPrimitive.Root;

interface TabsListProps extends React.ComponentPropsWithoutRef<typeof TabsPrimitive.List> {
  variant?: 'default' | 'pills' | 'underline';
}

const TabsList = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.List>,
  TabsListProps
>(({ className, variant = 'default', ...props }, ref) => {
  const variantStyles = {
    default: 'bg-gray-100 p-1 rounded-lg',
    pills: 'gap-2',
    underline: 'border-b border-gray-200 gap-4 w-fit',
  };

  return (
    <div className="overflow-x-auto scrollbar-hide">
      <TabsPrimitive.List
        ref={ref}
        className={cn('flex items-center', variantStyles[variant], className)}
        {...props}
      />
    </div>
  );
});

const TabsTrigger = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Trigger>,
  { variant?: 'default' | 'pills' | 'underline' } & React.ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger>
>(({ className, variant = 'default', ...props }, ref) => {
  const variantStyles = {
    default: cn(
      'px-3 py-1.5 text-sm rounded-md transition-colors',
      'data-[state=active]:bg-white data-[state=active]:text-gray-900'
    ),
    pills: cn(
      'px-2.5 py-1 text-xs rounded-full border transition-colors',
      'data-[state=active]:bg-primary-50 data-[state=active]:border-primary'
    ),
    underline: cn(
      'pb-2.5 border-b-2 border-transparent transition-colors',
      'data-[state=active]:text-primary data-[state=active]:border-primary'
    ),
  };

  return (
    <TabsPrimitive.Trigger
      ref={ref}
      className={cn('focus-visible:ring-2', variantStyles[variant], className)}
      {...props}
    />
  );
});
```

## Toast (components/ui/Toast.tsx)

```tsx
import * as ToastPrimitive from '@radix-ui/react-toast';
import { X, CheckCircle, XCircle, AlertTriangle } from 'lucide-react';
import { cn } from '@/lib/utils';

type ToastVariant = 'success' | 'error' | 'warning' | 'info';

const variantConfig: Record<ToastVariant, { icon: React.ReactNode; className: string }> = {
  success: {
    icon: <CheckCircle className="w-5 h-5 text-green-500" />,
    className: 'border-green-200 bg-green-50',
  },
  error: {
    icon: <XCircle className="w-5 h-5 text-red-500" />,
    className: 'border-red-200 bg-red-50',
  },
  warning: {
    icon: <AlertTriangle className="w-5 h-5 text-yellow-500" />,
    className: 'border-yellow-200 bg-yellow-50',
  },
  info: {
    icon: <Info className="w-5 h-5 text-blue-500" />,
    className: 'border-blue-200 bg-blue-50',
  },
};

export function Toast({ variant = 'info', title, description, onClose }) {
  const config = variantConfig[variant];

  return (
    <ToastPrimitive.Root
      className={cn(
        'flex items-start gap-3 rounded-lg border p-4 shadow-lg',
        'data-[state=open]:animate-slideIn data-[state=closed]:animate-slideOut',
        config.className
      )}
    >
      <div className="flex-shrink-0">{config.icon}</div>
      <div className="flex-1">
        {title && <ToastPrimitive.Title className="font-semibold">{title}</ToastPrimitive.Title>}
        <ToastPrimitive.Description className="text-sm">{description}</ToastPrimitive.Description>
      </div>
      <ToastPrimitive.Close onClick={onClose}>
        <X className="w-4 h-4" />
      </ToastPrimitive.Close>
    </ToastPrimitive.Root>
  );
}
```

## Tooltip (components/ui/Tooltip.tsx)

```tsx
import * as TooltipPrimitive from '@radix-ui/react-tooltip';
import { cn } from '@/lib/utils';

const TooltipProvider = TooltipPrimitive.Provider;
const Tooltip = TooltipPrimitive.Root;
const TooltipTrigger = TooltipPrimitive.Trigger;

const TooltipContent = React.forwardRef<
  React.ComponentRef<typeof TooltipPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof TooltipPrimitive.Content>
>(({ className, sideOffset = 4, ...props }, ref) => (
  <TooltipPrimitive.Portal>
    <TooltipPrimitive.Content
      ref={ref}
      sideOffset={sideOffset}
      className={cn(
        'z-50 bg-gray-900 text-white text-xs rounded-lg px-3 py-1.5 shadow-lg',
        'animate-in fade-in-0 zoom-in-95',
        'data-[state=closed]:animate-out data-[state=closed]:fade-out-0',
        className
      )}
      {...props}
    />
  </TooltipPrimitive.Portal>
));
```

## DropdownMenu (components/ui/DropdownMenu.tsx)

```tsx
import * as DropdownMenuPrimitive from '@radix-ui/react-dropdown-menu';
import { cn } from '@/lib/utils';

const DropdownMenu = DropdownMenuPrimitive.Root;
const DropdownMenuTrigger = DropdownMenuPrimitive.Trigger;

const DropdownMenuContent = React.forwardRef<
  React.ComponentRef<typeof DropdownMenuPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Content>
>(({ className, sideOffset = 4, ...props }, ref) => (
  <DropdownMenuPrimitive.Portal>
    <DropdownMenuPrimitive.Content
      ref={ref}
      sideOffset={sideOffset}
      className={cn(
        'z-50 min-w-[200px] rounded-lg border bg-white p-1 shadow-lg',
        'animate-in fade-in-0 zoom-in-95',
        className
      )}
      {...props}
    />
  </DropdownMenuPrimitive.Portal>
));

const DropdownMenuItem = React.forwardRef<
  React.ComponentRef<typeof DropdownMenuPrimitive.Item>,
  React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Item>
>(({ className, ...props }, ref) => (
  <DropdownMenuPrimitive.Item
    ref={ref}
    className={cn(
      'flex items-center gap-2 rounded-md px-2.5 py-2 text-sm cursor-pointer',
      'hover:bg-gray-100 focus:bg-gray-100 transition-colors',
      'data-[disabled]:opacity-50 data-[disabled]:pointer-events-none',
      className
    )}
    {...props}
  />
));
```

## Dependencies (package.json excerpt)

```json
{
  "dependencies": {
    "@radix-ui/react-dialog": "^1.1.15",
    "@radix-ui/react-dropdown-menu": "^2.1.16",
    "@radix-ui/react-select": "^2.2.6",
    "@radix-ui/react-slot": "^1.2.4",
    "@radix-ui/react-switch": "^1.2.6",
    "@radix-ui/react-tabs": "^1.1.13",
    "@radix-ui/react-toast": "^1.2.15",
    "@radix-ui/react-tooltip": "^1.2.8",
    "clsx": "^2.1.0",
    "tailwind-merge": "^2.2.0",
    "tailwindcss": "^4.0.0",
    "lucide-react": "^0.263.1"
  }
}
```
