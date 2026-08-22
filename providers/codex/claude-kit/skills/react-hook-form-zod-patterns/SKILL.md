---
name: react-hook-form-zod-patterns
description: Type-safe forms with react-hook-form and Zod validation — multi-step flows, mode switching, error display, schema composition. Use when building forms with runtime validation or multi-step signup/checkout.
---

Standardize form handling in React applications using react-hook-form with zodResolver for type-safe runtime validation, ensuring consistent error display, schema reuse, and multi-step form orchestration.

## When to use

- Building registration, login, password-change, or profile-edit forms with runtime validation
- Implementing multi-step forms (signup with email verification, checkout flows, onboarding wizards)
- Creating mode-switching forms (password vs OTP login, create vs edit, view vs edit)
- Setting up forms that sync state across tabs or conditional fields
- Migrating from Formik/Yup to react-hook-form/Zod
- Implementing inline edit forms (edit-in-place with expand/collapse)
- Ensuring form validation errors surface consistently in UI components
- Composing reusable validation schemas across domains

## Core conventions

1. **useForm with zodResolver**: Initialize with `useForm<SchemaType>({ resolver: zodResolver(schema), defaultValues: {...} })`. Infer TypeScript types via `z.infer<typeof schema>`. Never define form types manually—Zod is the single source of truth.

2. **Zod schemas with .strict() and .refine()**: Define schemas in a central `lib/validations.ts` or `schemas.ts` file. Use `.strict()` to reject unknown fields in production. Compose via `.extend()` for create vs update modes. Use `.refine()` for cross-field validation (e.g., `password === confirmPassword`). Export both the schema and the inferred type: `export const loginSchema = z.object({...}); export type LoginFormData = z.infer<typeof loginSchema>;`.

3. **Reusable validation rules**: Extract common patterns into reusable schemas or regex constants. Example: `const passwordSchema = z.string().min(8).max(100).regex(/[A-Z]/, 'Must contain uppercase').regex(/[a-z]/, 'Must contain lowercase').regex(/[0-9]/, 'Must contain digit')`. Reuse across login, signup, change-password, and reset-password schemas.

4. **Field registration with spread**: Use `{...register('fieldName')}` to bind input fields. For controlled inputs (e.g., custom components), use `value={...} onChange={...}` instead of register. Access errors via `formState.errors.fieldName?.message`.

5. **Error display inline**: Display field-level errors directly below the input via an `error` prop on the Input component. Example: `<Input label="Email" error={formState.errors.email?.message} {...register('email')} />`. Use consistent error styling (red text, red border) across the design system.

6. **handleSubmit wrapper**: Wrap onSubmit with `handleSubmit(onSubmit)`. The handler receives validated data; schema validation failures never reach onSubmit. Example: `<form onSubmit={handleSubmit(handleLogin)}>`. Inside the handler, destructure the validated payload: `const handleLogin = async (data: LoginFormData) => { await login(data.email, data.password); }`.

7. **Multi-step forms with separate useForm instances**: Each step maintains its own `useForm` instance. Example: signup step 1 (user details) → step 2 (OTP verification). Save validated data from step 1 into local state (`savedFormData`) and pass to step 2's API call. Do NOT share a single form instance across steps unless fields are truly shared.

8. **Mode switching (password vs OTP, create vs edit)**: Use separate `useForm` instances per mode. When switching modes, sync shared fields via `setValue`. Example: switching from password login to OTP login—copy the `identifier` field: `passwordForm.setValue('identifier', otpForm.getValues('identifier'))`. Use a state variable (`mode`) and conditional rendering for tabs.

9. **Conditional validation by mode**: For edit vs create, use the same schema but conditionally apply `.refine()` or `.optional()` for fields that differ. Alternatively, define separate schemas (`createSchema`, `updateSchema`) and compose via `.extend()` or `.omit()`. Example: password required on create, optional on update.

10. **formState.errors and formState.isDirty**: Access `formState.errors` for error messages, `formState.isDirty` to conditionally show Save/Cancel buttons, `formState.isValid` to disable Submit until valid. Watch specific fields with `watch(['field1', 'field2'])` to derive UI state (e.g., show Cancel only if any password field has content).

11. **reset() for clearing forms**: Call `reset()` to clear all fields and errors. Use `reset(defaultValues)` to reset to a specific state (e.g., when switching from edit mode back to view mode). For password-change forms, call `reset()` after successful submission and clear visibility toggles.

12. **getValues and setValue for manual sync**: Use `getValues('field')` to read current field value without triggering re-render. Use `setValue('field', value)` to programmatically update a field (e.g., when switching tabs, syncing identifier between password and OTP forms). Prefer `setValue` over directly mutating state.

13. **Schema-driven vs manual validation trade-offs**: Prefer Zod for all validation (required, min/max length, regex, cross-field). Manual validation (e.g., async email uniqueness check) should be rare and handled via `.refine()` or a separate API call before submit. Avoid duplicating validation logic in component state.

14. **Error handling in onSubmit**: Wrap API calls in try/catch. On error, display toast or set a local error state (e.g., `setOtpError()`). Do NOT call `setError()` on the form unless the error maps to a specific field (backend validation errors). Example: `catch (err) { if (err instanceof APIError) { showError(err.message); } }`.

15. **TypeScript types from Zod**: Always `export type FormData = z.infer<typeof schema>` alongside the schema. Never maintain separate TypeScript interface definitions for form data—Zod is the source of truth. Use these types in onSubmit handlers, API service signatures, and component props.

## Skeleton / example

```typescript
// lib/validations.ts
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

// Signup schema with cross-field validation
export const signupSchema = z
  .object({
    fullName: z.string().min(1, 'Full name is required').min(2, 'Full name must be at least 2 characters').max(100),
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

// Change password schema
export const changePasswordSchema = z
  .object({
    currentPassword: z.string().min(1, 'Current password is required'),
    newPassword: passwordSchema,
    confirmPassword: z.string().min(1, 'Please confirm your password'),
  })
  .refine((data) => data.newPassword === data.confirmPassword, {
    message: 'Passwords do not match',
    path: ['confirmPassword'],
  });

export type ChangePasswordFormData = z.infer<typeof changePasswordSchema>;
```

```tsx
// pages/LoginPage.tsx
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { loginSchema, type LoginFormData } from '@/lib/validations';
import { Input, Button } from '@/components/ui';
import { useAuthStore } from '@/stores/auth';
import { useToast } from '@/hooks/useToast';

function LoginPage() {
  const { login, isLoading } = useAuthStore();
  const { error: showError } = useToast();

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<LoginFormData>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: '', password: '' },
  });

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
      <Input
        label="Email"
        type="email"
        placeholder="you@example.com"
        error={errors.email?.message}
        {...register('email')}
      />
      <Input
        label="Password"
        type="password"
        placeholder="Enter password"
        error={errors.password?.message}
        {...register('password')}
      />
      <Button type="submit" isLoading={isLoading}>
        Sign In
      </Button>
    </form>
  );
}
```

```tsx
// pages/ChangePasswordPage.tsx
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { changePasswordSchema, type ChangePasswordFormData } from '@/lib/validations';
import { Input, Button } from '@/components/ui';
import { authService } from '@/lib/auth';
import { useToast } from '@/hooks/useToast';

function ChangePasswordPage() {
  const { success: showSuccess, error: showError } = useToast();
  const [showCurrentPassword, setShowCurrentPassword] = useState(false);
  const [showNewPassword, setShowNewPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);

  const {
    register,
    handleSubmit,
    formState: { errors },
    reset,
    watch,
  } = useForm<ChangePasswordFormData>({
    resolver: zodResolver(changePasswordSchema),
    defaultValues: { currentPassword: '', newPassword: '', confirmPassword: '' },
  });

  // Watch to conditionally show Cancel button
  const watchedPasswords = watch(['currentPassword', 'newPassword', 'confirmPassword']);
  const hasContent = watchedPasswords.some((val) => val && val.length > 0);

  const onSubmit = async (data: ChangePasswordFormData) => {
    try {
      await authService.changePassword(data.currentPassword, data.newPassword);
      reset();
      setShowCurrentPassword(false);
      setShowNewPassword(false);
      setShowConfirmPassword(false);
      showSuccess('Password updated successfully');
    } catch (err) {
      showError(err.message || 'Failed to change password');
    }
  };

  const handleCancel = () => {
    reset();
    setShowCurrentPassword(false);
    setShowNewPassword(false);
    setShowConfirmPassword(false);
  };

  return (
    <form onSubmit={handleSubmit(onSubmit)}>
      <Input
        label="Current Password"
        type={showCurrentPassword ? 'text' : 'password'}
        error={errors.currentPassword?.message}
        {...register('currentPassword')}
      />
      <Input
        label="New Password"
        type={showNewPassword ? 'text' : 'password'}
        error={errors.newPassword?.message}
        {...register('newPassword')}
      />
      <Input
        label="Confirm New Password"
        type={showConfirmPassword ? 'text' : 'password'}
        error={errors.confirmPassword?.message}
        {...register('confirmPassword')}
      />
      <div className="flex gap-2">
        {hasContent && (
          <Button type="button" variant="outline" onClick={handleCancel}>
            Cancel
          </Button>
        )}
        <Button type="submit">Update Password</Button>
      </div>
    </form>
  );
}
```

```tsx
// pages/MultiStepSignupPage.tsx - separate useForm per step
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { signupSchema, type SignupFormData } from '@/lib/validations';
import { Input, Button, OTPInput } from '@/components/ui';
import { useAuthStore } from '@/stores/auth';

function MultiStepSignupPage() {
  const [step, setStep] = useState<1 | 2>(1);
  const [savedFormData, setSavedFormData] = useState<SignupFormData | null>(null);
  const [otp, setOtp] = useState('');
  const { signUp, verifyEmailAndCreate, isLoading } = useAuthStore();

  // Step 1 form
  const step1Form = useForm<SignupFormData>({
    resolver: zodResolver(signupSchema),
    defaultValues: { fullName: '', email: '', phone: '', password: '', confirmPassword: '' },
  });

  const handleStep1Submit = async (data: SignupFormData) => {
    await signUp(data);
    setSavedFormData(data);
    setStep(2);
  };

  const handleStep2Submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (otp.length !== 6 || !savedFormData) return;
    await verifyEmailAndCreate(savedFormData.email, otp);
  };

  return step === 1 ? (
    <form onSubmit={step1Form.handleSubmit(handleStep1Submit)}>
      <Input label="Full Name" error={step1Form.formState.errors.fullName?.message} {...step1Form.register('fullName')} />
      <Input label="Email" error={step1Form.formState.errors.email?.message} {...step1Form.register('email')} />
      <Input label="Phone" error={step1Form.formState.errors.phone?.message} {...step1Form.register('phone')} />
      <Input label="Password" type="password" error={step1Form.formState.errors.password?.message} {...step1Form.register('password')} />
      <Input label="Confirm Password" type="password" error={step1Form.formState.errors.confirmPassword?.message} {...step1Form.register('confirmPassword')} />
      <Button type="submit" isLoading={isLoading}>Continue</Button>
    </form>
  ) : (
    <form onSubmit={handleStep2Submit}>
      <OTPInput value={otp} onChange={setOtp} />
      <Button type="submit" disabled={otp.length !== 6} isLoading={isLoading}>
        Verify & Create Account
      </Button>
    </form>
  );
}
```

## Anti-patterns to avoid

1. **Defining form types separately from schemas**: never maintain a separate TypeScript interface for form data—use `z.infer<typeof schema>` to derive types from Zod schemas. This is the single source of truth.
2. **Sharing a single useForm across unrelated steps**: each step in a multi-step form should have its own `useForm` instance unless fields are truly shared. Save validated step 1 data into state, then pass to step 2's API call.
3. **Not using .refine() for cross-field validation**: password confirmation, date range checks, and conditional required fields should use `.refine()` on the schema, not manual checks in onSubmit.
4. **Calling setError manually for validation logic**: prefer Zod schema validation over manual `setError()` calls. Use `setError()` only for server-side validation errors that map to specific fields.
5. **Mixing controlled and uncontrolled inputs**: use `{...register('field')}` for native inputs; for custom components, use `value={...} onChange={...}` and `setValue`. Don't mix both on the same field.
6. **Not resetting form after successful submit**: call `reset()` after successful password change, profile update, or multi-step completion to clear fields and errors.
7. **Duplicating validation regex in components**: extract reusable patterns (email, phone, password strength) into schema constants in `lib/validations.ts`, not in component state.
8. **Not displaying field-level errors**: always pass `formState.errors.fieldName?.message` to the Input component's `error` prop. Generic "form invalid" messages are insufficient.
9. **Using watch() excessively**: `watch()` triggers re-renders. Use it sparingly for conditional UI (e.g., show Cancel if any field has content). Prefer `getValues()` for one-time reads.
10. **Not leveraging schema composition**: use `.extend()`, `.omit()`, `.pick()`, or `.partial()` to compose create/update schemas from a base schema. Don't duplicate field definitions across schemas.

## References

- [form-setup-and-zod.md](references/form-setup-and-zod.md) — useForm setup, zodResolver, schema definition, and type inference
- [multi-step-and-modes.md](references/multi-step-and-modes.md) — multi-step forms, mode switching (password vs OTP, create vs edit), and conditional validation
- [repo-evidence.md](references/repo-evidence.md) — source file patterns and snippets

Cross-references:
- `frontend-repo-architecture` — project structure, design system integration, and API client patterns
- `frontend-ui-engineering` — accessible Input/Button components, error styling, and form layout patterns
