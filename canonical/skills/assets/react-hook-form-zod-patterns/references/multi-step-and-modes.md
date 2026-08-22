# Multi-step forms and mode switching

## Multi-step forms with separate useForm instances

Each step maintains its own `useForm` instance. Save validated data from step 1 into local state, then pass to step 2's API call.

```tsx
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { signupSchema, type SignupFormData } from '@/lib/validations';

function MultiStepSignupPage() {
  const [step, setStep] = useState<1 | 2>(1);
  const [savedFormData, setSavedFormData] = useState<SignupFormData | null>(null);
  const [otp, setOtp] = useState('');
  const { signUp, verifyEmailAndCreate, isLoading } = useAuthStore();

  // Step 1: user details form
  const step1Form = useForm<SignupFormData>({
    resolver: zodResolver(signupSchema),
    defaultValues: { fullName: '', email: '', phone: '', password: '', confirmPassword: '' },
  });

  const handleStep1Submit = async (data: SignupFormData) => {
    try {
      await signUp(data);
      setSavedFormData(data);
      setStep(2);
    } catch (err) {
      showError(err.message);
    }
  };

  const handleStep2Submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (otp.length !== 6 || !savedFormData) return;
    try {
      await verifyEmailAndCreate(savedFormData.email, otp);
      navigate('/');
    } catch (err) {
      showError(err.message);
    }
  };

  return step === 1 ? (
    <form onSubmit={step1Form.handleSubmit(handleStep1Submit)}>
      <Input label="Full Name" error={step1Form.formState.errors.fullName?.message} {...step1Form.register('fullName')} />
      <Input label="Email" error={step1Form.formState.errors.email?.message} {...step1Form.register('email')} />
      <Input label="Phone" error={step1Form.formState.errors.phone?.message} {...step1Form.register('phone')} />
      <Input label="Password" type="password" error={step1Form.formState.errors.password?.message} {...step1Form.register('password')} />
      <Input label="Confirm Password" type="password" error={step1Form.formState.errors.confirmPassword?.message} {...step1Form.register('confirmPassword')} />
      <Button type="submit" isLoading={isLoading}>Continue & Verify Email</Button>
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

- **Separate forms**: `step1Form` for user details, no form instance for step 2 (OTP is a simple controlled input).
- **savedFormData**: Store step 1's validated data in local state to pass to step 2's API call.
- **Conditional rendering**: Use `step === 1 ? <Step1> : <Step2>` to switch between steps.

## Mode switching (password vs OTP login)

Use separate `useForm` instances per mode and sync shared fields when switching:

```tsx
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { loginSchema, loginOtpSchema, type LoginFormData, type LoginOtpFormData } from '@/lib/validations';

function LoginPage() {
  const [mode, setMode] = useState<'password' | 'otp'>('password');

  // Password login form
  const passwordForm = useForm<LoginFormData>({
    resolver: zodResolver(loginSchema),
    defaultValues: { identifier: '', password: '' },
  });

  // OTP login form (only identifier)
  const otpForm = useForm<LoginOtpFormData>({
    resolver: zodResolver(loginOtpSchema),
    defaultValues: { identifier: '' },
  });

  const handleModeSwitch = (newMode: 'password' | 'otp') => {
    // Sync identifier between forms
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
    <Tabs value={mode} onValueChange={(v) => handleModeSwitch(v as 'password' | 'otp')}>
      <TabsList>
        <TabsTrigger value="password">Password</TabsTrigger>
        <TabsTrigger value="otp">OTP</TabsTrigger>
      </TabsList>

      <TabsContent value="password">
        <form onSubmit={passwordForm.handleSubmit(handlePasswordLogin)}>
          <Input label="Email or phone" error={passwordForm.formState.errors.identifier?.message} {...passwordForm.register('identifier')} />
          <Input label="Password" type="password" error={passwordForm.formState.errors.password?.message} {...passwordForm.register('password')} />
          <Button type="submit">Sign In</Button>
        </form>
      </TabsContent>

      <TabsContent value="otp">
        <form onSubmit={otpForm.handleSubmit(handleSendOTP)}>
          <Input label="Email or phone" error={otpForm.formState.errors.identifier?.message} {...otpForm.register('identifier')} />
          <Button type="submit">Send Login Code</Button>
        </form>
      </TabsContent>
    </Tabs>
  );
}
```

- **Separate forms per mode**: `passwordForm` and `otpForm` have different schemas.
- **handleModeSwitch**: Reads the current `identifier` from the active form and writes it to the new form via `setValue`.
- **Tabs component**: Use a controlled Tabs component to switch modes.

## Conditional validation (create vs edit)

For edit vs create, use the same schema but conditionally apply validation:

```typescript
// Create schema: password required
export const createUserSchema = z.object({
  fullName: z.string().min(1),
  email: z.string().email(),
  password: passwordSchema,
});

// Update schema: password optional
export const updateUserSchema = z.object({
  fullName: z.string().min(1),
  email: z.string().email(),
  password: passwordSchema.optional(),
});
```

Or compose from a base schema:

```typescript
const baseUserSchema = z.object({
  fullName: z.string().min(1),
  email: z.string().email(),
});

export const createUserSchema = baseUserSchema.extend({
  password: passwordSchema,
  confirmPassword: z.string().min(1),
}).refine((data) => data.password === data.confirmPassword, {
  message: 'Passwords do not match',
  path: ['confirmPassword'],
});

export const updateUserSchema = baseUserSchema.extend({
  phone: z.string().optional(),
});
```

- **Separate schemas**: Define `createSchema` and `updateSchema` with different field requirements.
- **Schema composition**: Use `.extend()` to add fields; `.omit()` to remove; `.partial()` to make all optional.

## View vs edit mode switching

Toggle between view and edit mode in the same form:

```tsx
function ProfilePage() {
  const user = useAuthStore((s) => s.user);
  const [isEditing, setIsEditing] = useState(false);
  const [firstName, setFirstName] = useState(user?.firstName ?? '');
  const [lastName, setLastName] = useState(user?.lastName ?? '');

  const handleStartEdit = () => {
    setFirstName(user?.firstName ?? '');
    setLastName(user?.lastName ?? '');
    setIsEditing(true);
  };

  const handleCancelEdit = () => {
    setFirstName(user?.firstName ?? '');
    setLastName(user?.lastName ?? '');
    setIsEditing(false);
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    await updateProfile({ firstName, lastName });
    setIsEditing(false);
  };

  return (
    <form onSubmit={handleSave}>
      <Input
        label="First Name"
        value={firstName}
        onChange={(e) => setFirstName(e.target.value)}
        disabled={!isEditing}
      />
      <Input
        label="Last Name"
        value={lastName}
        onChange={(e) => setLastName(e.target.value)}
        disabled={!isEditing}
      />
      {isEditing ? (
        <div className="flex gap-2">
          <Button type="button" variant="outline" onClick={handleCancelEdit}>Cancel</Button>
          <Button type="submit">Save Changes</Button>
        </div>
      ) : (
        <Button type="button" onClick={handleStartEdit}>Edit</Button>
      )}
    </form>
  );
}
```

- **isEditing state**: Toggles between view and edit mode.
- **disabled prop**: Inputs are disabled when not editing.
- **handleCancelEdit**: Resets local state to original user values.

## Using watch() for conditional UI

Use `watch()` to conditionally show UI based on field values:

```tsx
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

// Watch all password fields
const watchedPasswords = watch(['currentPassword', 'newPassword', 'confirmPassword']);
const hasContent = watchedPasswords.some((val) => val && val.length > 0);

return (
  <form onSubmit={handleSubmit(onSubmit)}>
    <Input label="Current Password" type="password" error={errors.currentPassword?.message} {...register('currentPassword')} />
    <Input label="New Password" type="password" error={errors.newPassword?.message} {...register('newPassword')} />
    <Input label="Confirm Password" type="password" error={errors.confirmPassword?.message} {...register('confirmPassword')} />
    <div className="flex gap-2">
      {hasContent && (
        <Button type="button" variant="outline" onClick={() => reset()}>
          Cancel
        </Button>
      )}
      <Button type="submit">Update Password</Button>
    </div>
  </form>
);
```

- **watch(['field1', 'field2'])**: Returns an array of current values; triggers re-render on change.
- **Conditional Cancel button**: Only show Cancel if any password field has content.
- **Avoid excessive watch()**: Use sparingly; prefer `getValues()` for one-time reads.

## Resend OTP countdown timer

Track a countdown timer to prevent rapid resends:

```tsx
const [resendCountdown, setResendCountdown] = useState(0);

const startResendTimer = useCallback(() => {
  setResendCountdown(60);
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

const handleResendOTP = async () => {
  if (resendCountdown > 0) return;
  await signUp(savedFormData);
  startResendTimer();
  setOtp('');
};

return (
  <div>
    <OTPInput value={otp} onChange={setOtp} />
    {resendCountdown > 0 ? (
      <span>Resend in {formatCountdown(resendCountdown)}</span>
    ) : (
      <button onClick={handleResendOTP}>Resend Code</button>
    )}
  </div>
);
```

- **resendCountdown**: Tracks seconds remaining; decrements every 1000ms.
- **startResendTimer**: Starts the countdown after sending OTP.
- **Conditional button**: Disable resend while countdown > 0.
