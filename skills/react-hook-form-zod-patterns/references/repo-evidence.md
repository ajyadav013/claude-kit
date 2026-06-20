# Repo evidence

SHORT, GENERICIZED snippets from production frontends demonstrating react-hook-form + Zod patterns. File paths are generic placeholders; no internal service/repo names.

---

## Login with password and OTP modes

File: `frontend/src/pages/auth/LoginPage.tsx`

```tsx
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { loginSchema, loginOtpSchema, type LoginFormData, type LoginOtpFormData } from '@/lib/validations';

type LoginMode = 'password' | 'otp';

function LoginPage() {
  const [mode, setMode] = useState<LoginMode>('password');

  const passwordForm = useForm<LoginFormData>({
    resolver: zodResolver(loginSchema),
    defaultValues: { identifier: '', password: '' },
  });

  const otpForm = useForm<LoginOtpFormData>({
    resolver: zodResolver(loginOtpSchema),
    defaultValues: { identifier: '' },
  });

  const handleModeSwitch = (newMode: LoginMode) => {
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

  const handlePasswordLogin = async (data: LoginFormData) => {
    await login(data.identifier, data.password);
    navigate('/');
  };

  const handleSendOTP = async (data: LoginOtpFormData) => {
    await sendOTP(data.identifier);
    navigate('/verify-otp', { state: { identifier: data.identifier } });
  };

  return (
    <Tabs value={mode} onValueChange={(v) => handleModeSwitch(v as LoginMode)}>
      <TabsList>
        <TabsTrigger value="password">Password</TabsTrigger>
        <TabsTrigger value="otp">OTP</TabsTrigger>
      </TabsList>

      <TabsContent value="password">
        <form onSubmit={passwordForm.handleSubmit(handlePasswordLogin)}>
          <Input
            label="Email or phone"
            error={passwordForm.formState.errors.identifier?.message}
            {...passwordForm.register('identifier')}
          />
          <Input
            label="Password"
            type="password"
            error={passwordForm.formState.errors.password?.message}
            {...passwordForm.register('password')}
          />
          <Button type="submit">Sign In</Button>
        </form>
      </TabsContent>

      <TabsContent value="otp">
        <form onSubmit={otpForm.handleSubmit(handleSendOTP)}>
          <Input
            label="Email or phone"
            error={otpForm.formState.errors.identifier?.message}
            {...otpForm.register('identifier')}
          />
          <Button type="submit">Send Login Code</Button>
        </form>
      </TabsContent>
    </Tabs>
  );
}
```

**Pattern**: Separate `useForm` instances for password and OTP modes; sync shared `identifier` field via `getValues`/`setValue` when switching tabs.

---

## Multi-step signup with email verification

File: `frontend/src/pages/auth/SignUpPage.tsx`

```tsx
import { useState, useCallback } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { signUpSchema, type SignUpSchemaData } from '@/lib/validations';

type SignUpStep = 1 | 2;
const RESEND_COUNTDOWN = 60;

function SignUpPage() {
  const [step, setStep] = useState<SignUpStep>(1);
  const [otp, setOtp] = useState('');
  const [savedFormData, setSavedFormData] = useState<SignUpFormData | null>(null);
  const [resendCountdown, setResendCountdown] = useState(0);

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<SignUpSchemaData>({
    resolver: zodResolver(signUpSchema),
    defaultValues: {
      fullName: '',
      email: '',
      phone: '',
      password: '',
      confirmPassword: '',
    },
  });

  const startResendTimer = useCallback(() => {
    setResendCountdown(RESEND_COUNTDOWN);
    const interval = setInterval(() => {
      setResendCountdown((prev) => {
        if (prev <= 1) {
          clearInterval(interval);
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
  }, []);

  const handleStep1Submit = async (data: SignUpSchemaData) => {
    const formData: SignUpFormData = {
      fullName: data.fullName,
      email: data.email,
      phone: data.phone,
      password: data.password,
      confirmPassword: data.confirmPassword,
    };

    await signUp(formData);
    setSavedFormData(formData);
    setStep(2);
    startResendTimer();
  };

  const handleVerifyAndCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (otp.length !== 6 || !savedFormData) return;

    await verifyEmailAndCreateAccount(savedFormData.email, otp);
    navigate('/');
  };

  const handleResendOTP = async () => {
    if (resendCountdown > 0 || !savedFormData) return;
    await signUp(savedFormData);
    startResendTimer();
    setOtp('');
  };

  return step === 1 ? (
    <form onSubmit={handleSubmit(handleStep1Submit)}>
      <Input label="Full name" error={errors.fullName?.message} {...register('fullName')} />
      <Input label="Email" error={errors.email?.message} {...register('email')} />
      <Input label="Phone" error={errors.phone?.message} {...register('phone')} />
      <Input label="Password" type="password" error={errors.password?.message} {...register('password')} />
      <Input label="Confirm Password" type="password" error={errors.confirmPassword?.message} {...register('confirmPassword')} />
      <Button type="submit">Continue & Verify Email</Button>
    </form>
  ) : (
    <form onSubmit={handleVerifyAndCreate}>
      <OTPInput value={otp} onChange={setOtp} />
      <div>
        {resendCountdown > 0 ? (
          <span>Resend in {formatCountdown(resendCountdown)}</span>
        ) : (
          <button type="button" onClick={handleResendOTP}>Resend code</button>
        )}
      </div>
      <Button type="submit" disabled={otp.length !== 6}>
        Verify & Create Account
      </Button>
      <button type="button" onClick={() => setStep(1)}>&larr; Back</button>
    </form>
  );
}
```

**Pattern**: Step 1 uses `useForm` with Zod validation; step 2 is a simple controlled OTP input. Save step 1's validated data in `savedFormData` and pass to step 2's API call.

---

## Profile page with edit mode and change password

File: `frontend/src/pages/settings/ProfilePage.tsx`

```tsx
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { changePasswordSchema, type ChangePasswordFormData } from '@/lib/validations';

function ProfilePage() {
  const user = useAuthStore((s) => s.user);
  const updateProfile = useAuthStore((s) => s.updateProfile);

  // Profile edit state
  const [isEditingProfile, setIsEditingProfile] = useState(false);
  const [firstName, setFirstName] = useState(user?.first_name ?? '');
  const [lastName, setLastName] = useState(user?.last_name ?? '');
  const [phone, setPhone] = useState(user?.phone ?? '');

  // Password form
  const passwordForm = useForm<ChangePasswordFormData>({
    resolver: zodResolver(changePasswordSchema),
    defaultValues: {
      current_password: '',
      new_password: '',
      confirm_password: '',
    },
  });

  // Watch password fields to conditionally show Cancel button
  const watchedPasswords = passwordForm.watch(['current_password', 'new_password', 'confirm_password']);
  const hasPasswordContent = watchedPasswords.some((val) => val && val.length > 0);

  const handleSaveProfile = async (e: React.FormEvent) => {
    e.preventDefault();
    await updateProfile({
      first_name: firstName || undefined,
      last_name: lastName || undefined,
      phone: phone || undefined,
    });
    setIsEditingProfile(false);
  };

  const handleChangePassword = async (data: ChangePasswordFormData) => {
    await authService.changePassword(data.current_password, data.new_password);
    passwordForm.reset();
  };

  const handleClearPasswordForm = () => {
    passwordForm.reset();
  };

  return (
    <div>
      {/* Personal Information Section */}
      <div>
        <h2>Personal Information</h2>
        {!isEditingProfile && (
          <Button onClick={() => setIsEditingProfile(true)}>Edit</Button>
        )}
        <form onSubmit={handleSaveProfile}>
          <Input
            label="First name"
            value={isEditingProfile ? firstName : (user?.first_name ?? '')}
            onChange={(e) => setFirstName(e.target.value)}
            disabled={!isEditingProfile}
          />
          <Input
            label="Last name"
            value={isEditingProfile ? lastName : (user?.last_name ?? '')}
            onChange={(e) => setLastName(e.target.value)}
            disabled={!isEditingProfile}
          />
          <Input label="Email" value={user?.email} disabled />
          <Input
            label="Phone"
            value={isEditingProfile ? phone : (user?.phone ?? '')}
            onChange={(e) => setPhone(e.target.value)}
            disabled={!isEditingProfile}
          />
          {isEditingProfile && (
            <div>
              <Button type="button" variant="outline" onClick={() => setIsEditingProfile(false)}>Cancel</Button>
              <Button type="submit">Save Changes</Button>
            </div>
          )}
        </form>
      </div>

      {/* Change Password Section */}
      <div>
        <h2>Change Password</h2>
        <form onSubmit={passwordForm.handleSubmit(handleChangePassword)}>
          <Input
            label="Current password"
            type="password"
            error={passwordForm.formState.errors.current_password?.message}
            {...passwordForm.register('current_password')}
          />
          <Input
            label="New password"
            type="password"
            error={passwordForm.formState.errors.new_password?.message}
            {...passwordForm.register('new_password')}
          />
          <Input
            label="Confirm new password"
            type="password"
            error={passwordForm.formState.errors.confirm_password?.message}
            {...passwordForm.register('confirm_password')}
          />
          <div>
            {hasPasswordContent && (
              <Button type="button" variant="ghost" onClick={handleClearPasswordForm}>Cancel</Button>
            )}
            <Button type="submit">Update Password</Button>
          </div>
        </form>
      </div>
    </div>
  );
}
```

**Pattern**: Profile edit uses controlled inputs (no `useForm`); password change uses `useForm` with zodResolver. `watch()` tracks password fields to conditionally show Cancel button.

---

## Zod validation schemas

File: `frontend/src/lib/validations.ts`

```typescript
import { z } from 'zod';

const phoneRegex = /^\+?[\d\s-]{10,}$/;
const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function isEmail(value: string): boolean {
  return emailRegex.test(value);
}

export function isPhone(value: string): boolean {
  return phoneRegex.test(value);
}

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
  identifier: z
    .string()
    .min(1, 'Email or phone number is required')
    .refine(
      (value) => isEmail(value) || isPhone(value),
      'Please enter a valid email or phone number'
    ),
  password: z
    .string()
    .min(1, 'Password is required')
    .min(8, 'Password must be at least 8 characters'),
});

export type LoginFormData = z.infer<typeof loginSchema>;

// OTP login schema
export const loginOtpSchema = z.object({
  identifier: z
    .string()
    .min(1, 'Email or phone number is required')
    .refine(
      (value) => isEmail(value) || isPhone(value),
      'Please enter a valid email or phone number'
    ),
});

export type LoginOtpFormData = z.infer<typeof loginOtpSchema>;

// Signup schema with cross-field validation
export const signUpSchema = z
  .object({
    fullName: z
      .string()
      .min(1, 'Full name is required')
      .min(2, 'Full name must be at least 2 characters')
      .max(100, 'Full name must be at most 100 characters'),
    email: z
      .string()
      .min(1, 'Email address is required')
      .email('Please enter a valid email address'),
    phone: z
      .string()
      .min(1, 'Phone number is required')
      .regex(phoneRegex, 'Please enter a valid phone number'),
    password: passwordSchema,
    confirmPassword: z.string().min(1, 'Please confirm your password'),
  })
  .refine((data) => data.password === data.confirmPassword, {
    message: 'Passwords do not match',
    path: ['confirmPassword'],
  });

export type SignUpSchemaData = z.infer<typeof signUpSchema>;

// Change password schema
export const changePasswordSchema = z
  .object({
    current_password: z.string().min(1, 'Current password is required'),
    new_password: passwordSchema,
    confirm_password: z.string().min(1, 'Please confirm your password'),
  })
  .refine((data) => data.new_password === data.confirm_password, {
    message: 'Passwords do not match',
    path: ['confirm_password'],
  });

export type ChangePasswordFormData = z.infer<typeof changePasswordSchema>;
```

**Pattern**: Reusable `passwordSchema` composed into login, signup, and change-password schemas. Cross-field validation via `.refine()`. TypeScript types inferred via `z.infer<typeof schema>`.

---

## File paths (genericized)

All internal service/repo names have been replaced with generic placeholders:

- `frontend/src/pages/auth/LoginPage.tsx` — multi-mode login (password vs OTP)
- `frontend/src/pages/auth/SignUpPage.tsx` — multi-step signup with email verification
- `frontend/src/pages/settings/ProfilePage.tsx` — profile edit with change password
- `frontend/src/lib/validations.ts` — Zod schemas and reusable validation rules
- `frontend/src/components/ui/Input.tsx` — Input component with inline error display
- `frontend/src/components/ui/Button.tsx` — Button component with loading state
- `frontend/src/components/ui/OTPInput.tsx` — 6-digit OTP input component
- `frontend/src/components/ui/Tabs.tsx` — Tabs component for mode switching
