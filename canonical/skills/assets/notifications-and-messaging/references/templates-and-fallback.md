# Templates and Fallback

Template-driven messages, OTP flows, calendar invites, and retry/fallback patterns.

## Template functions

Define templates as functions that return `{ subject, html, text }`:

```typescript
// services/notifications/email-templates.ts
export interface EmailTemplate {
  subject: string;
  html: string;
  text: string;
}

export const verificationOtpEmail = (name: string, otp: string): EmailTemplate => ({
  subject: 'Verify your email',
  html: `
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
      <h1 style="color: #333;">Hi ${name},</h1>
      <p>Your verification code is:</p>
      <div style="background: #f4f4f4; padding: 20px; text-align: center; font-size: 32px; font-weight: bold; letter-spacing: 5px;">
        ${otp}
      </div>
      <p style="color: #666; font-size: 14px;">This code is valid for 30 minutes.</p>
      <p style="color: #999; font-size: 12px;">If you did not request this, please ignore this email.</p>
    </div>
  `,
  text: `Hi ${name},\n\nYour verification code is: ${otp}\n\nThis code is valid for 30 minutes.\n\nIf you did not request this, please ignore this email.`,
});

export const passwordResetOtpEmail = (name: string, otp: string): EmailTemplate => ({
  subject: 'Reset your password',
  html: `
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
      <h1 style="color: #333;">Hi ${name},</h1>
      <p>You requested to reset your password. Use the code below to continue:</p>
      <div style="background: #fff3cd; border: 2px solid #ffc107; padding: 20px; text-align: center; font-size: 32px; font-weight: bold; letter-spacing: 5px;">
        ${otp}
      </div>
      <p style="color: #666; font-size: 14px;">This code expires in 10 minutes.</p>
      <p style="color: #999; font-size: 12px;">If you did not request a password reset, please contact support immediately.</p>
    </div>
  `,
  text: `Hi ${name},\n\nYou requested to reset your password. Use this code: ${otp}\n\nThis code expires in 10 minutes.`,
});

export const interviewScheduledEmail = (data: {
  candidateName: string;
  jobTitle: string;
  companyName: string;
  interviewDate: string;
  interviewTime: string;
  interviewType: string;
  meetingLink?: string;
}): EmailTemplate => ({
  subject: `Interview Scheduled: ${data.jobTitle} at ${data.companyName}`,
  html: `
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
      <h1 style="color: #333;">Hi ${data.candidateName},</h1>
      <p>Your interview for <strong>${data.jobTitle}</strong> at ${data.companyName} has been scheduled.</p>
      <div style="background: #e8f5e9; padding: 20px; border-left: 4px solid #4caf50;">
        <h2 style="margin-top: 0;">${data.interviewType}</h2>
        <p><strong>Date:</strong> ${data.interviewDate}</p>
        <p><strong>Time:</strong> ${data.interviewTime}</p>
        ${data.meetingLink ? `<p><strong>Meeting Link:</strong> <a href="${data.meetingLink}">${data.meetingLink}</a></p>` : ''}
      </div>
      <p style="margin-top: 20px;">A calendar invite is attached. Good luck!</p>
      <p style="color: #999; font-size: 12px;">If you need to reschedule, please contact your recruiter.</p>
    </div>
  `,
  text: `Hi ${data.candidateName},\n\nYour interview for ${data.jobTitle} at ${data.companyName} is scheduled:\n\nType: ${data.interviewType}\nDate: ${data.interviewDate}\nTime: ${data.interviewTime}${data.meetingLink ? `\nMeeting Link: ${data.meetingLink}` : ''}\n\nA calendar invite is attached. Good luck!`,
});

export const offerExpiringEmail = (data: {
  candidateName: string;
  jobTitle: string;
  companyName: string;
  offerExpiryDate?: string;
}): EmailTemplate => ({
  subject: `Action Required: Your offer for ${data.jobTitle} expires soon`,
  html: `
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
      <h1 style="color: #333;">Hi ${data.candidateName},</h1>
      <p>Your offer for <strong>${data.jobTitle}</strong> at ${data.companyName} expires soon.</p>
      ${data.offerExpiryDate ? `<p style="background: #fff3cd; padding: 15px; border-left: 4px solid #ffc107;"><strong>Expiry Date:</strong> ${data.offerExpiryDate}</p>` : ''}
      <p>Please review and respond to your offer in the candidate portal.</p>
      <p style="color: #999; font-size: 12px;">If you have questions, contact your recruiter.</p>
    </div>
  `,
  text: `Hi ${data.candidateName},\n\nYour offer for ${data.jobTitle} at ${data.companyName} expires soon.${data.offerExpiryDate ? `\n\nExpiry Date: ${data.offerExpiryDate}` : ''}\n\nPlease review and respond to your offer in the candidate portal.`,
});
```

## iCal/ICS calendar invite generation

```typescript
// services/calendar/ical.ts
export interface CalendarEvent {
  summary: string;
  description: string;
  startTime: Date;
  endTime: Date;
  location?: string;
  meetingUrl?: string;
  attendeeEmail: string;
  attendeeName?: string;
  organizerEmail: string;
  organizerName?: string;
}

export const generateIcsContent = (event: CalendarEvent): string => {
  const formatDate = (date: Date) => {
    return date.toISOString().replace(/[-:]/g, '').split('.')[0] + 'Z';
  };

  const uid = `${Date.now()}-${Math.random().toString(36).substring(7)}@myapp.com`;
  const location = event.meetingUrl || event.location || 'Virtual';

  return `BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//MyApp//Interview Scheduler//EN
METHOD:REQUEST
BEGIN:VEVENT
UID:${uid}
DTSTAMP:${formatDate(new Date())}
DTSTART:${formatDate(event.startTime)}
DTEND:${formatDate(event.endTime)}
SUMMARY:${event.summary}
DESCRIPTION:${event.description}
LOCATION:${location}
ORGANIZER;CN=${event.organizerName || 'Recruiter'}:mailto:${event.organizerEmail}
ATTENDEE;CN=${event.attendeeName || 'Candidate'};RSVP=TRUE:mailto:${event.attendeeEmail}
STATUS:CONFIRMED
SEQUENCE:0
END:VEVENT
END:VCALENDAR`;
};
```

**Usage with SendGrid:**

```typescript
// services/email/index.ts
import { generateIcsContent } from '../calendar/ical.js';
import { interviewScheduledEmail } from '../notifications/email-templates.js';

async function sendInterviewInvite(candidate: Candidate, interview: Interview) {
  const template = interviewScheduledEmail({
    candidateName: candidate.name,
    jobTitle: interview.job.title,
    companyName: interview.org.name,
    interviewDate: interview.scheduledAt.toLocaleDateString('en-US'),
    interviewTime: interview.scheduledAt.toLocaleTimeString('en-US'),
    interviewType: interview.type,
    meetingLink: interview.meetingUrl,
  });

  const icsContent = generateIcsContent({
    summary: `Interview: ${interview.job.title}`,
    description: `${interview.type} with ${interview.org.name}`,
    startTime: interview.scheduledAt,
    endTime: new Date(interview.scheduledAt.getTime() + interview.durationMinutes * 60000),
    meetingUrl: interview.meetingUrl,
    attendeeEmail: candidate.email,
    attendeeName: candidate.name,
    organizerEmail: 'recruiter@company.com',
    organizerName: 'Recruiting Team',
  });

  const icsBase64 = Buffer.from(icsContent).toString('base64');

  await sendGridService.sendEmail({
    to: candidate.email,
    subject: template.subject,
    html: template.html,
    text: template.text,
    // Inline for Gmail/Outlook auto-recognition
    calendarContent: icsContent,
    // Attachment for other clients
    attachments: [{
      filename: 'interview.ics',
      content: icsBase64,
      type: 'text/calendar; method=REQUEST',
      disposition: 'attachment',
    }],
  });
}
```

**SendGrid multipart content structure:**

```typescript
// services/sendgrid/index.ts (excerpt)
async sendEmail(options: SendEmailOptions): Promise<SendGridResponse> {
  const content: Array<{ type: string; value: string }> = [];

  // Add plain text first (lowest priority in multipart/alternative)
  if (options.text) {
    content.push({ type: 'text/plain', value: options.text });
  }

  // Add HTML content
  content.push({ type: 'text/html', value: options.html });

  // Add calendar content for Gmail/Outlook auto-recognition
  // This must be the last content type for proper calendar detection
  if (options.calendarContent) {
    content.push({
      type: 'text/calendar; method=REQUEST',
      value: options.calendarContent,
    });
  }

  const msg = {
    to: Array.isArray(options.to) ? options.to : [options.to],
    from: options.from || this.defaultFrom,
    subject: options.subject,
    content,
  };

  // Add attachments (including .ics file)
  if (options.attachments && options.attachments.length > 0) {
    msg.attachments = options.attachments.map((att) => ({
      content: att.content,
      filename: att.filename,
      type: att.type,
      disposition: att.disposition || 'attachment',
    }));
  }

  const [response] = await sgMail.send(msg);
  return { success: true, data: response };
}
```

## OTP flow with Redis and retry

```typescript
// services/auth/otp.service.ts
import { Redis } from 'ioredis';

const redis = new Redis(process.env.REDIS_URL);

const OTP_PREFIX = 'otp:verify-email:';
const OTP_EXPIRY = 30 * 60; // 30 minutes in seconds

export async function sendVerificationOtp(email: string, name: string): Promise<boolean> {
  const otp = Math.floor(100000 + Math.random() * 900000).toString(); // 6-digit OTP
  const key = `${OTP_PREFIX}${otp}`;

  // Store OTP in Redis with TTL
  await redis.set(key, email, 'EX', OTP_EXPIRY);

  const template = verificationOtpEmail(name, otp);

  const result = await emailService.sendEmail({
    to: email,
    subject: template.subject,
    html: template.html,
    text: template.text,
  });

  if (!result.success) {
    console.error('[OTP] Failed to send verification email:', result.message);
    // Don't delete Redis key — allow retry
  }

  return result.success;
}

export async function verifyOtp(otp: string): Promise<string | null> {
  const key = `${OTP_PREFIX}${otp}`;
  const email = await redis.get(key);

  if (!email) {
    return null; // Invalid or expired OTP
  }

  // Delete OTP after verification (single use)
  await redis.del(key);

  return email;
}
```

## Retry with fallback provider

```typescript
// services/email/retry.service.ts
export async function retryOnFailure<T>(
  fn: (provider: string, options: T) => Promise<EmailResponse>,
  primaryProvider: string,
  fallbackProvider: string,
  options: T
): Promise<EmailResponse> {
  try {
    const result = await fn(primaryProvider, options);
    if (result.success) {
      return result;
    }
    console.warn(`[Retry] Primary provider ${primaryProvider} failed, trying fallback ${fallbackProvider}`);
  } catch (error: any) {
    console.error(`[Retry] Primary provider ${primaryProvider} error:`, error.message);
  }

  // Fallback to secondary provider
  try {
    const result = await fn(fallbackProvider, options);
    if (result.success) {
      console.log(`[Retry] Fallback provider ${fallbackProvider} succeeded`);
      return result;
    }
    console.error(`[Retry] Fallback provider ${fallbackProvider} also failed`);
    return result;
  } catch (error: any) {
    console.error(`[Retry] Fallback provider ${fallbackProvider} error:`, error.message);
    return { success: false, message: `Both providers failed: ${error.message}` };
  }
}

// Usage
await retryOnFailure(
  (provider, opts) => emailService.sendEmail(opts, provider),
  'sendgrid',
  'smtp',
  {
    to: 'user@example.com',
    subject: 'Hello',
    html: '<p>World</p>',
  }
);
```

## E.164 phone number formatting

```typescript
// services/sms/phone-formatter.ts
export interface FormattedPhone {
  countryCode: string;
  phoneNumber: string;
  fullNumber: string;
}

export function formatPhoneNumber(phone: string, defaultCountryCode: string = '1'): FormattedPhone {
  // Remove all non-digit characters except +
  let cleaned = phone.replace(/[^\d+]/g, '');

  // Remove leading + if present
  if (cleaned.startsWith('+')) {
    cleaned = cleaned.substring(1);
  }

  // If starts with 0, remove it (local number format)
  if (cleaned.startsWith('0')) {
    cleaned = cleaned.substring(1);
  }

  // If it's 10 digits, assume default country (e.g., India: 91, US: 1)
  if (cleaned.length === 10) {
    return {
      countryCode: defaultCountryCode,
      phoneNumber: cleaned,
      fullNumber: defaultCountryCode + cleaned,
    };
  }

  // If it already starts with country code
  if (cleaned.length > 10 && cleaned.startsWith(defaultCountryCode)) {
    return {
      countryCode: defaultCountryCode,
      phoneNumber: cleaned.substring(defaultCountryCode.length),
      fullNumber: cleaned,
    };
  }

  // Otherwise, prepend default country code
  return {
    countryCode: defaultCountryCode,
    phoneNumber: cleaned,
    fullNumber: defaultCountryCode + cleaned,
  };
}

// Usage
const { fullNumber } = formatPhoneNumber('9876543210', '91');
// fullNumber: '919876543210'

const { fullNumber: usNumber } = formatPhoneNumber('(555) 123-4567', '1');
// usNumber: '15551234567'
```

## Cron-based interview reminders

```typescript
// services/notifications/cron-reminders.ts
export async function sendInterviewReminders(prisma: PrismaClient): Promise<void> {
  const now = new Date();
  const tomorrow = new Date(now.getTime() + 24 * 60 * 60 * 1000);
  const dayAfterTomorrow = new Date(now.getTime() + 48 * 60 * 60 * 1000);

  try {
    // Find all interviews scheduled for tomorrow (24-48 hours from now)
    const interviews = await prisma.interview.findMany({
      where: {
        scheduledAt: {
          gte: tomorrow,
          lt: dayAfterTomorrow,
        },
        status: 'SCHEDULED',
      },
      include: {
        candidate: {
          include: {
            notificationPrefs: true,
          },
        },
        job: {
          include: {
            org: true,
          },
        },
      },
    });

    console.log(`[Reminders] Found ${interviews.length} interviews for tomorrow`);

    for (const interview of interviews) {
      const { candidate, job } = interview;

      // Check if reminders are enabled for this candidate
      if (candidate.notificationPrefs && !candidate.notificationPrefs.interviewScheduled) {
        console.log(`[Reminders] Interview reminders disabled for candidate ${candidate.id}`);
        continue;
      }

      const interviewDate = interview.scheduledAt.toLocaleDateString('en-US', {
        weekday: 'long',
        year: 'numeric',
        month: 'long',
        day: 'numeric',
      });
      const interviewTime = interview.scheduledAt.toLocaleTimeString('en-US', {
        hour: '2-digit',
        minute: '2-digit',
        timeZoneName: 'short',
      });

      const template = interviewReminderEmail({
        candidateName: candidate.name,
        jobTitle: job.title,
        companyName: job.org?.name || 'the company',
        interviewDate,
        interviewTime,
        interviewType: interview.type,
        meetingLink: interview.meetingUrl,
      });

      const success = await emailService.sendEmail({
        to: candidate.email,
        subject: template.subject,
        html: template.html,
        text: template.text,
      });

      if (success) {
        console.log(`[Reminders] Sent interview reminder to ${candidate.email}`);
      }
    }
  } catch (error) {
    console.error('[Reminders] Error sending interview reminders:', error);
  }
}

// Schedule via cron (e.g., daily at 9am)
// 0 9 * * * /usr/bin/node /app/scripts/send-reminders.js
```

## Notification preferences check

```typescript
// services/notifications/notification.service.ts
export type NotificationType =
  | 'WELCOME'
  | 'VERIFICATION_OTP'
  | 'PASSWORD_RESET_OTP'
  | 'APPLICATION_UPDATE'
  | 'INTERVIEW_SCHEDULED'
  | 'INTERVIEW_REMINDER'
  | 'OFFER_RECEIVED'
  | 'OFFER_EXPIRING'
  | 'NEW_MESSAGE';

const notificationPreferenceMap: Record<NotificationType, string | null> = {
  WELCOME: null, // Always send
  VERIFICATION_OTP: null, // Always send
  PASSWORD_RESET_OTP: null, // Always send
  APPLICATION_UPDATE: 'applicationUpdates',
  INTERVIEW_SCHEDULED: 'interviewScheduled',
  INTERVIEW_REMINDER: 'interviewScheduled',
  OFFER_RECEIVED: 'offerReceived',
  OFFER_EXPIRING: 'offerReminders',
  NEW_MESSAGE: 'recruiterMessages',
};

async function isNotificationEnabled(
  prisma: PrismaClient,
  userId: string,
  notificationType: NotificationType
): Promise<boolean> {
  const prefField = notificationPreferenceMap[notificationType];

  // Always send for types that don't have preferences
  if (prefField === null) {
    return true;
  }

  const prefs = await prisma.notificationPrefs.findUnique({
    where: { userId },
  });

  // Default to true if no preferences exist
  if (!prefs) {
    return true;
  }

  // Check the specific preference field
  return (prefs as Record<string, unknown>)[prefField] === true;
}

export async function sendNotification(
  prisma: PrismaClient,
  payload: {
    userId: string;
    type: NotificationType;
    data: Record<string, any>;
  }
): Promise<boolean> {
  // Check if notification type is enabled
  const isEnabled = await isNotificationEnabled(prisma, payload.userId, payload.type);
  if (!isEnabled) {
    console.log(`[Notification] ${payload.type} is disabled for user ${payload.userId}`);
    return false;
  }

  // Build template based on type
  let template: EmailTemplate;
  switch (payload.type) {
    case 'VERIFICATION_OTP':
      template = verificationOtpEmail(payload.data.name, payload.data.otp);
      break;
    case 'INTERVIEW_SCHEDULED':
      template = interviewScheduledEmail(payload.data);
      break;
    // ... other cases
  }

  // Send via email service
  const result = await emailService.sendEmail({
    to: payload.data.email,
    subject: template.subject,
    html: template.html,
    text: template.text,
  });

  console.log(`[Notification] ${payload.type} sent to ${payload.data.email}:`, result.success);
  return result.success;
}
```
