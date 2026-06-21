# Form setup and Zod schema patterns

## useForm with zodResolver

Initialize react-hook-form with zodResolver to bind Zod schema validation:

```typescript
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { loginSchema, type LoginFormData } from '@/lib/validations';

const {
  register,
  handleSubmit,
  formState: { errors },
  reset,
  watch,
  getValues,
  setValue,
} = useForm<LoginFormData>({
  resolver: zodResolver(loginSchema),
  defaultValues: {
    email: '',
    password: '',
  },
});
```

- **resolver**: `zodResolver(schema)` enforces validation before onSubmit.
- **defaultValues**: Always provide initial values to avoid uncontrolled → controlled warnings.
- **Generic type**: `useForm<SchemaType>` ensures type safety throughout the form.

## Zod schema definition

Define schemas in a central `lib/validations.ts` file:

```typescript
import { z } from 'zod';

// Reusable password schema
export const passwordSchema = z
  .string()
  .min(1, 'Password is required')
  .min(8, 'Password must be at least 8 characters')
  .max(100, 'Password must be at most 100 characters')
  .regex(/[A-Z]/, 'Password must contain at least one uppercase letter')
  .regex(/[a-z]/, 'Password must contain at least one lowercase letter')
  .regex(/[0-9]/, 'Password must contain at least one number');

// Login schema
export const loginSchema = z.object({
  email: z.string().min(1, 'Email is required').email('Invalid email address'),
  password: z.string().min(1, 'Password is required').min(8, 'Password must be at least 8 characters'),
});

export type LoginFormData = z.infer<typeof loginSchema>;
```

- **Reusable schemas**: Extract common patterns (email, phone, password) into standalone schemas.
- **Type inference**: `z.infer<typeof schema>` derives TypeScript types from the schema.
- **Export both**: Export the schema and the inferred type together.

## Cross-field validation with .refine()

Use `.refine()` for validation that depends on multiple fields:

```typescript
export const signupSchema = z
  .object({
    fullName: z.string().min(1, 'Full name is required').min(2).max(100),
    email: z.string().min(1, 'Email is required').email('Invalid email address'),
    phone: z.string().min(1, 'Phone is required').regex(/^\+?[\d\s-]{10,}$/, 'Invalid phone number'),
    password: passwordSchema,
    confirmPassword: z.string().min(1, 'Please confirm your password'),
  })
  .refine((data) => data.password === data.confirmPassword, {
    message: 'Passwords do not match',
    path: ['confirmPassword'],
  });

export type SignupFormData = z.infer<typeof signupSchema>;
```

- **.refine()**: Takes a predicate `(data) => boolean` and an error config `{ message, path }`.
- **path**: Specifies which field receives the error (here, `confirmPassword`).
- **Common use cases**: password confirmation, date ranges, conditional required fields.

## Schema composition

Compose schemas via `.extend()`, `.omit()`, `.pick()`, or `.partial()`:

```typescript
// Base user schema
const baseUserSchema = z.object({
  email: z.string().email(),
  fullName: z.string().min(1),
});

// Create schema extends base
export const createUserSchema = baseUserSchema.extend({
  password: passwordSchema,
  confirmPassword: z.string().min(1),
}).refine((data) => data.password === data.confirmPassword, {
  message: 'Passwords do not match',
  path: ['confirmPassword'],
});

// Update schema omits password fields
export const updateUserSchema = baseUserSchema.extend({
  phone: z.string().optional(),
});
```

- **extend()**: Add new fields to an existing schema.
- **omit()**: Remove fields from a schema.
- **partial()**: Make all fields optional (useful for patch updates).

## Field registration and error display

Bind fields with `{...register('fieldName')}` and display errors inline:

```tsx
<Input
  label="Email"
  type="email"
  placeholder="you@example.com"
  error={formState.errors.email?.message}
  {...register('email')}
/>
```

- **register()**: Returns `{ name, ref, onChange, onBlur }` for native inputs.
- **formState.errors**: Keyed by field name; each error has a `message` string.
- **error prop**: Pass to the Input component for consistent error styling.

## handleSubmit wrapper

Wrap onSubmit with `handleSubmit(onSubmit)`:

```tsx
const onSubmit = async (data: LoginFormData) => {
  try {
    await login(data.email, data.password);
    navigate('/dashboard');
  } catch (err) {
    showError(err.message || 'Login failed');
  }
};

return (
  <form onSubmit={handleSubmit(onSubmit)}>
    {/* fields */}
    <Button type="submit">Sign In</Button>
  </form>
);
```

- **handleSubmit**: Validates against the Zod schema; only calls onSubmit if valid.
- **onSubmit receives validated data**: No need to check validation errors inside onSubmit.
- **Error handling**: Wrap API calls in try/catch; display errors via toast or local state.

## reset() for clearing forms

Call `reset()` to clear all fields and errors:

```typescript
const handleCancel = () => {
  reset();
  setShowPassword(false);
};
```

- **reset()**: Clears to `defaultValues` and resets `formState`.
- **reset(newDefaults)**: Resets to a new set of values (e.g., when switching from edit to view).
- **Use after submit**: Always reset after successful password change or profile update.

## getValues() and setValue() for manual sync

Use `getValues()` for one-time reads and `setValue()` for programmatic updates:

```typescript
// Sync identifier between password and OTP forms when switching modes
const handleModeSwitch = (newMode: 'password' | 'otp') => {
  const currentIdentifier =
    mode === 'password'
      ? passwordForm.getValues('identifier')
      : otpForm.getValues('identifier');

  setMode(newMode);

  if (newMode === 'password') {
    passwordForm.setValue('identifier', currentIdentifier);
  } else {
    otpForm.setValue('identifier', currentIdentifier);
  }
};
```

- **getValues()**: Reads current value without triggering re-render.
- **setValue()**: Programmatically updates a field; triggers validation if `shouldValidate: true`.
- **Use for mode switching**: Sync shared fields when switching between tabs or modes.
