---
name: notifications-and-messaging
description: Multi-provider notification delivery for email and SMS — provider abstraction, fallback chains, template-driven messages (OTP, verification, calendar invites). Use when building notification systems.
---

Standardize multi-provider notification delivery across email (SendGrid, Nodemailer, AWS SES) and SMS (Twilio, provider-specific APIs) with provider abstraction, template-driven messages, and graceful degradation.

## When to use

- Building a notification system with multiple delivery channels (email, SMS)
- Integrating SendGrid, Nodemailer, AWS SES, or Twilio for transactional emails/SMS
- Implementing OTP delivery via email or SMS with expiry and retry logic
- Sending calendar invites (.ics / iCal format) embedded in emails for interview scheduling or meetings
- Creating a provider abstraction layer to switch between email/SMS vendors
- Setting up ENV-driven provider selection and fallback chains (primary → secondary on failure)
- Implementing dev-mode logging instead of actual delivery for local testing
- Formatting phone numbers to E.164 standard for international SMS delivery
- Building template-driven notification workflows (welcome, verification, password reset, reminders)
- Adding notification preferences and opt-in/opt-out management

## Core conventions

1. **Provider abstraction layer**: define a common interface for each channel (email, SMS) and implement per-provider adapters. Email providers: `SendGridProvider`, `NodemailerProvider`, `SESProvider`. SMS providers: `TwilioProvider`, `VendorSpecificSmsProvider`. Each provider exposes `sendEmail(options)` or `sendSms(options)` returning `{ success: boolean, message?: string, data?: any }`.

2. **Singleton pattern for provider instances**: use `getInstance()` to ensure a single provider instance per process. Check ENV config in constructor (`EMAIL_PROVIDER`, `SMS_PROVIDER`, `SENDGRID_API_KEY`, `SMTP_HOST`, etc.). If credentials missing and `NODE_ENV === "development"`, log warnings and enable dev-mode fallback; otherwise throw errors.

3. **Auto-discovery via directory scan**: load provider modules dynamically via `fs.readdirSync(__dirname)` filtering for `*.provider.js` files, require each, and register in a `providers` object keyed by filename prefix (e.g., `sendgrid.provider.js` → `providers.sendgrid`). Dispatcher function `sendMail(providerName, emailContent)` invokes `providers[providerName].sendMail(emailContent)`.

4. **ENV-driven provider selection**: read `process.env.EMAIL_PROVIDER` (default `"sendgrid"`) or `process.env.SMS_PROVIDER` to determine the active provider. Normalize to lowercase, trim whitespace. Only initialize the selected provider's SDK (e.g., `sgMail.setApiKey()` only when `EMAIL_PROVIDER === "sendgrid"`). Log which provider is active at startup.

5. **Dev-mode logging instead of sending**: when `NODE_ENV === "development"` or `DISABLE_EMAIL === "true"`, skip actual API calls. Log email/SMS details to console (recipient, subject, preview of HTML/text, OTP codes) and return `{ success: true, message: "Logged (dev mode)" }`. Useful for local testing without burning quota or exposing credentials.

6. **Fallback chain for high availability**: wrap provider calls in a retry/fallback wrapper (`retryOnFailure(fn, provider, options)`) that attempts the primary provider, then falls back to a secondary provider on failure. Example: SendGrid primary → Nodemailer SMTP secondary. Track failure counters and alert on repeated fallback usage. **Caveat — a provider-wide outage flips *all* traffic to the secondary at once**, so size the secondary for full load (or accept shedding) and exercise the fallback path regularly; an untested fallback that can't absorb the surge amplifies the outage instead of surviving it. See the fallback-amplification / static-stability note in `.claude/rules/resilience-engineering.md`.

7. **Template-driven messages**: define templates as functions that accept data objects and return `{ subject, html, text }`. Common templates: `verificationOtpEmail(name, otp)`, `passwordResetEmail(name, resetLink)`, `welcomeEmail(name, portalLink)`, `interviewScheduledEmail(candidate, job, interviewDate, meetingLink)`, `offerExpiringEmail(candidate, job, expiryDate)`. Use a template engine (Nunjucks, Handlebars, or inline string templates) for HTML generation. Store templates in `templates/` or `src/templates/emails/`.

8. **OTP and verification flows**: generate OTP codes (typically 6-digit numeric or alphanumeric), store in Redis with TTL (`SET otp:verify-email:{code} {userId} EX 1800`), send via email or SMS, and verify via `GET otp:verify-email:{code}` then `DEL` on success. Template includes expiry time ("valid for 30 minutes"). For email, template function `verificationOtpEmail(name, otp, expiryMinutes)` returns HTML/text with the code prominently displayed.

9. **Calendar invites via iCal/ICS format**: for interview scheduling, generate `.ics` content with `text/calendar; method=REQUEST` MIME type. Include `VEVENT` with `UID`, `SUMMARY`, `DTSTART`, `DTEND`, `LOCATION` (or `DESCRIPTION` with meeting link), `ORGANIZER`, `ATTENDEE`. Attach as both a `text/calendar` content part (for Gmail/Outlook auto-recognition) and as an attachment `interview.ics` (base64-encoded). SendGrid example: `content: [{ type: 'text/html', value: html }, { type: 'text/calendar; method=REQUEST', value: icsContent }]` plus `attachments: [{ filename: 'interview.ics', content: icsBase64, type: 'text/calendar' }]`.

10. **E.164 phone number formatting**: before sending SMS, normalize phone numbers to E.164 format (`+<country_code><number>`, e.g., `+919876543210`). Strip non-digits except `+`, remove leading `0`, prepend default country code (e.g., `91` for India) if 10 digits. Helper function `formatPhoneNumber(phone, countryCode = "91")` returns `{ countryCode, phoneNumber, fullNumber }`. Validation: reject if length < 10 or > 15 after formatting.

11. **Notification preferences and opt-out**: check user preferences before sending non-critical notifications (e.g., `notificationPrefs.applicationUpdates`, `notificationPrefs.interviewReminders`). Always send OTP, verification, and password reset (bypass preferences). Store preferences in DB (`CandidateNotificationPrefs` table with boolean fields per notification type). Map notification types to preference fields via `notificationPreferenceMap: Record<NotificationType, string | null>` where `null` means "always send".

12. **Batch/bulk sending**: for SMS, use bulk API endpoints when available (e.g., `sendBulkSms(messages: Array<{ to, message, templateId }>)`) to reduce overhead. For email, use SendGrid's batch send or multiple `to` addresses in a single API call when sending identical content to multiple recipients. Track per-message delivery status.

13. **Retry and error handling**: wrap provider API calls in try/catch. Log errors with context (recipient, provider, error message). Return structured response `{ success: false, message: error.message }` on failure. For transient errors (rate limits, timeouts), implement exponential backoff retry. For permanent errors (invalid credentials, blocked recipient), log and alert but don't retry.

14. **Cron-based reminders**: schedule periodic jobs (via cron or task scheduler) to send reminders (e.g., interview reminder 24h before, offer expiry reminder 24h before deadline). Query DB for upcoming events in the time window, filter by user preferences, build notification payloads, and send via the notification service. Example: `sendInterviewReminders(prisma)` finds interviews scheduled for tomorrow, sends reminder emails to candidates with `interviewScheduled` preference enabled.

15. **Logging and observability**: log every send attempt with recipient (masked: `user@*****.com`), notification type, provider, and result. Track metrics: total sent, delivery success rate, fallback invocations, per-provider failure counts. Use structured logging (JSON) for easy querying. Optional: integrate with external observability (Sentry, New Relic) for error tracking.

## Skeleton / example

```typescript
// services/email-provider/index.ts
import { readdirSync } from 'fs';
import path from 'path';

const providers: Record<string, any> = {};
const providerFiles = readdirSync(__dirname)
  .filter((f) => f.includes('provider.') && f.endsWith('.js'));

providerFiles.forEach((file) => {
  const name = file.split('.')[0]; // e.g., "sendgrid" from "sendgrid.provider.js"
  providers[name] = require(`./${file}`);
});

// Dispatcher
export const sendMail = (provider: string, emailContent: EmailContent) => 
  providers[provider].sendMail(emailContent);
```

```typescript
// services/email-provider/sendgrid.provider.ts
import sgMail from '@sendgrid/mail';

const apiKey = process.env.SENDGRID_API_KEY || '';
const emailProvider = (process.env.EMAIL_PROVIDER || 'sendgrid').toLowerCase();
const isDevelopment = process.env.NODE_ENV === 'development';

if (emailProvider === 'sendgrid' && apiKey) {
  sgMail.setApiKey(apiKey);
  console.log('[SendGrid] API key configured');
} else if (emailProvider === 'sendgrid' && isDevelopment) {
  console.warn('[SendGrid] API key not set - emails will be logged in dev mode');
}

export const sendMail = async ({ email, subject, bodyHtml }: EmailContent) => {
  if (isDevelopment && !apiKey) {
    console.log('[DEV MODE] Email would be sent:', { to: email, subject, preview: bodyHtml.substring(0, 100) });
    return { success: true, message: 'Logged (dev mode)' };
  }

  try {
    await sgMail.send({
      to: email,
      from: process.env.EMAIL_FROM_EMAIL || 'noreply@example.com',
      subject,
      html: bodyHtml,
    });
    console.log('[SendGrid] Email sent to:', email);
    return { success: true };
  } catch (error: any) {
    console.error('[SendGrid] Error:', error.message);
    return { success: false, message: error.message };
  }
};
```

```typescript
// services/email-provider/nodemailer.provider.ts (SMTP fallback)
import nodemailer from 'nodemailer';

const transporter = nodemailer.createTransport({
  host: process.env.SMTP_HOST,
  port: Number(process.env.SMTP_PORT || 587),
  secure: true,
  auth: {
    user: process.env.SMTP_USER,
    pass: process.env.SMTP_PASS,
  },
});

export const sendMail = async ({ email, subject, bodyHtml }: EmailContent) => {
  try {
    const info = await transporter.sendMail({
      from: process.env.SMTP_FROM_EMAIL,
      to: email,
      subject,
      html: bodyHtml,
    });
    console.log('[Nodemailer] Email sent:', info.messageId);
    return { success: true, data: info };
  } catch (error: any) {
    console.error('[Nodemailer] Error:', error.message);
    return { success: false, message: error.message };
  }
};
```

```typescript
// services/sms/sms.service.ts (singleton with E.164 formatting)
export class SmsService {
  private static instance: SmsService;
  private apiKey: string;
  private senderId: string;
  private isConfigured: boolean = false;

  constructor() {
    this.apiKey = process.env.SMS_API_KEY || '';
    this.senderId = process.env.SMS_SENDER_ID || '';
    this.isConfigured = !!(this.apiKey && this.senderId);

    if (this.isConfigured) {
      console.log('[SMS] Service configured');
    } else {
      console.warn('[SMS] Service not configured. Set SMS_API_KEY and SMS_SENDER_ID.');
    }
  }

  public static getInstance(): SmsService {
    if (!SmsService.instance) {
      SmsService.instance = new SmsService();
    }
    return SmsService.instance;
  }

  private formatPhoneNumber(phone: string, countryCode: string = '1'): { fullNumber: string } {
    let cleaned = phone.replace(/[^\d+]/g, '');
    if (cleaned.startsWith('+')) cleaned = cleaned.substring(1);
    if (cleaned.startsWith('0')) cleaned = cleaned.substring(1);

    // If 10 digits, prepend country code
    if (cleaned.length === 10) {
      return { fullNumber: countryCode + cleaned };
    }
    // If already starts with country code
    if (cleaned.startsWith(countryCode)) {
      return { fullNumber: cleaned };
    }
    // Otherwise prepend
    return { fullNumber: countryCode + cleaned };
  }

  async sendSms(to: string, message: string, options: { smsType?: 'otp' | 'transaction' } = {}) {
    if (!this.isConfigured) {
      return { success: false, message: 'SMS service not configured' };
    }

    const { fullNumber } = this.formatPhoneNumber(to);

    try {
      // Call SMS provider API (pseudo-code)
      const response = await fetch(process.env.SMS_API_URL!, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          to: fullNumber,
          from: this.senderId,
          body: message,
          sms_type: options.smsType === 'otp' ? 'O' : 'T',
        }),
      });

      console.log('[SMS] Sent to:', fullNumber);
      return { success: true };
    } catch (error: any) {
      console.error('[SMS] Error:', error.message);
      return { success: false, message: error.message };
    }
  }

  async sendOtp(phone: string, code: string, expiryMinutes: number) {
    const message = `Your verification code is: ${code}. This code expires in ${expiryMinutes} minutes.`;
    return this.sendSms(phone, message, { smsType: 'otp' });
  }
}

export const smsService = SmsService.getInstance();
```

```typescript
// services/notifications/templates.ts
export interface EmailTemplate {
  subject: string;
  html: string;
  text: string;
}

export const verificationOtpEmail = (name: string, otp: string, expiryMinutes: number = 30): EmailTemplate => ({
  subject: 'Verify your email',
  html: `
    <h1>Hi ${name},</h1>
    <p>Your verification code is: <strong style="font-size: 24px;">${otp}</strong></p>
    <p>This code is valid for ${expiryMinutes} minutes.</p>
    <p>If you did not request this, please ignore this email.</p>
  `,
  text: `Hi ${name},\n\nYour verification code is: ${otp}\n\nThis code is valid for ${expiryMinutes} minutes.`,
});

export const interviewScheduledEmail = (data: {
  candidateName: string;
  jobTitle: string;
  companyName: string;
  interviewDate: string;
  interviewTime: string;
  meetingLink?: string;
}): EmailTemplate => ({
  subject: `Interview Scheduled: ${data.jobTitle}`,
  html: `
    <h1>Hi ${data.candidateName},</h1>
    <p>Your interview for <strong>${data.jobTitle}</strong> at ${data.companyName} has been scheduled.</p>
    <ul>
      <li>Date: ${data.interviewDate}</li>
      <li>Time: ${data.interviewTime}</li>
      ${data.meetingLink ? `<li>Meeting Link: <a href="${data.meetingLink}">${data.meetingLink}</a></li>` : ''}
    </ul>
    <p>Good luck!</p>
  `,
  text: `Hi ${data.candidateName},\n\nYour interview for ${data.jobTitle} at ${data.companyName} is scheduled on ${data.interviewDate} at ${data.interviewTime}.${data.meetingLink ? `\n\nMeeting Link: ${data.meetingLink}` : ''}`,
});
```

```typescript
// services/notifications/calendar.ts (iCal generation)
export const generateIcsContent = (event: {
  summary: string;
  description: string;
  startTime: Date;
  endTime: Date;
  location?: string;
  attendeeEmail: string;
  organizerEmail: string;
}): string => {
  const formatDate = (date: Date) => date.toISOString().replace(/[-:]/g, '').split('.')[0] + 'Z';

  return `BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//MyApp//Interview Scheduler//EN
METHOD:REQUEST
BEGIN:VEVENT
UID:${Date.now()}@myapp.com
DTSTAMP:${formatDate(new Date())}
DTSTART:${formatDate(event.startTime)}
DTEND:${formatDate(event.endTime)}
SUMMARY:${event.summary}
DESCRIPTION:${event.description}
LOCATION:${event.location || 'Virtual'}
ORGANIZER;CN=Recruiter:mailto:${event.organizerEmail}
ATTENDEE;CN=Candidate;RSVP=TRUE:mailto:${event.attendeeEmail}
STATUS:CONFIRMED
SEQUENCE:0
END:VEVENT
END:VCALENDAR`;
};

// Usage in email service
const icsContent = generateIcsContent({
  summary: 'Interview: Software Engineer',
  description: 'Technical interview with the engineering team.',
  startTime: new Date('2026-06-25T10:00:00Z'),
  endTime: new Date('2026-06-25T11:00:00Z'),
  location: 'https://meet.google.com/abc-defg',
  attendeeEmail: 'candidate@example.com',
  organizerEmail: 'recruiter@company.com',
});

await sendGridService.sendEmail({
  to: 'candidate@example.com',
  subject: 'Interview Scheduled',
  html: '<p>You have an interview scheduled.</p>',
  calendarContent: icsContent, // Inline for Gmail/Outlook auto-recognition
  attachments: [{
    filename: 'interview.ics',
    content: Buffer.from(icsContent).toString('base64'),
    type: 'text/calendar; method=REQUEST',
  }],
});
```

```typescript
// services/notifications/notification.service.ts (preference-aware dispatch)
export type NotificationType =
  | 'WELCOME'
  | 'VERIFICATION_OTP'
  | 'PASSWORD_RESET_OTP'
  | 'INTERVIEW_SCHEDULED'
  | 'OFFER_EXPIRING';

const notificationPreferenceMap: Record<NotificationType, string | null> = {
  WELCOME: null, // Always send
  VERIFICATION_OTP: null, // Always send
  PASSWORD_RESET_OTP: null, // Always send
  INTERVIEW_SCHEDULED: 'interviewScheduled',
  OFFER_EXPIRING: 'offerReminders',
};

export async function sendNotification(
  prisma: PrismaClient,
  userId: string,
  type: NotificationType,
  data: Record<string, any>
) {
  // Check preferences
  const prefField = notificationPreferenceMap[type];
  if (prefField !== null) {
    const prefs = await prisma.notificationPrefs.findUnique({ where: { userId } });
    if (prefs && !prefs[prefField]) {
      console.log(`[Notification] ${type} disabled for user ${userId}`);
      return false;
    }
  }

  // Build template
  let template: EmailTemplate;
  switch (type) {
    case 'VERIFICATION_OTP':
      template = verificationOtpEmail(data.name, data.otp);
      break;
    case 'INTERVIEW_SCHEDULED':
      template = interviewScheduledEmail(data);
      break;
    // ... other cases
  }

  // Send via provider
  const result = await emailProvider.sendMail('sendgrid', {
    email: data.email,
    subject: template.subject,
    bodyHtml: template.html,
  });

  console.log(`[Notification] ${type} sent to ${data.email}:`, result.success);
  return result.success;
}
```

## Anti-patterns to avoid

1. **Hardcoded provider credentials in code**: load from ENV variables or secrets manager.
2. **No dev-mode fallback**: without dev-mode logging, local testing requires valid API keys and burns quota.
3. **Ignoring notification preferences for all types**: OTP/verification/password reset should always send; marketing/reminders should respect opt-out.
4. **Not normalizing phone numbers to E.164**: many SMS providers require E.164; send failures or incorrect delivery otherwise.
5. **Embedding OTP codes in query params or URLs**: security risk; always send OTP in email/SMS body, never in clickable links.
6. **Not setting TTL on OTP Redis keys**: unbounded key growth; always use `EX` for expiry.
7. **Sending calendar invites without both inline and attachment**: Gmail/Outlook auto-recognition requires `text/calendar` content part; some clients need `.ics` attachment.
8. **No retry or fallback on provider failure**: single-provider dependency creates outages; implement fallback chain or retry logic.
9. **Logging full recipient email/phone in production**: mask sensitive data in logs (`user@*****.com`, `+91*****1234`).
10. **Not validating email/phone before sending**: bad data causes API errors and wastes quota; validate format upfront.
11. **Using SendGrid/Twilio test credentials in production**: separate test/production keys to avoid accidental quota burn or delivery to real users in test environments.
12. **Not tracking send metrics**: without metrics, you can't detect delivery issues, provider outages, or preference trends.

## References

- [repo-evidence.md](references/repo-evidence.md) — source file paths and genericized snippets
- [provider-abstraction.md](references/provider-abstraction.md) — auto-discovery, ENV-driven selection, singleton pattern
- [templates-and-fallback.md](references/templates-and-fallback.md) — template functions, iCal generation, OTP flows, retry/fallback patterns
