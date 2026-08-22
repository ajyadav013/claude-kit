# Repo Evidence

Genericized snippets from real production services demonstrating notification patterns. All internal identifiers (service names, repos, infrastructure) have been removed or replaced with placeholders.

## Provider auto-discovery

**Directory structure:**

```
app/
  common/
    email-provider/
      index.js
      sendgrid.provider.js
      smtp.provider.js
```

**Auto-discovery loader (app/common/email-provider/index.js):**

```javascript
const { readdirSync } = require('fs');
const path = require('path');

const providers = {};
const getProviderFiles = (source) => readdirSync(source, { withFileTypes: true })
  .filter((dirent) => !dirent.isDirectory() && dirent.name.includes('provider'))
  .map((dirent) => dirent.name);

const providerFiles = getProviderFiles(path.resolve(__dirname, './'));

providerFiles.forEach((file) => {
  providers[file.split('.')[0]] = require(`./${file}`);
});

exports.sendMail = (provider, emailContent) => providers[provider].sendMail(emailContent);
```

**SendGrid provider (app/common/email-provider/sendgrid.provider.js):**

```javascript
const sgMail = require('@sendgrid/mail');
const config = require('../../../config');

if (config.emailProvider === 'sendgrid') sgMail.setApiKey(config.sendGrid.apiKey);

const logger = require('../winston')('email-provider');
const { EMAIL_SENDER } = require('../constants');

exports.sendMail = ({ email, subject, bodyHtml }) => {
  logger.info(`Sending Email via SENDGRID to:${email} sub:${subject}`);
  const msg = {
    to: email,
    from: EMAIL_SENDER,
    subject,
    html: bodyHtml,
  };

  return sgMail.send(msg);
};
```

**Nodemailer SMTP provider (app/common/email-provider/smtp.provider.js):**

```javascript
const nodemailer = require('nodemailer');
const logger = require('../winston')('smtp');
const config = require('../../../config');

const transporter = nodemailer.createTransport({
  host: config.get('smtp.host'),
  port: config.get('smtp.port'),
  secure: true,
  auth: {
    user: config.get('smtp.user'),
    pass: config.get('smtp.pass')
  }
});

exports.sendMail = async ({ email, subject, bodyHtml }) => {
  logger.info(`Sending Email via SMTP to:${email} sub:${subject}`);
  const mailOptions = {
    from: config.get('smtp.fromEmail'),
    to: email,
    subject,
    html: bodyHtml
  };
  const res = await transporter.sendMail(mailOptions);
  logger.info(`Email to ${email}`, { meta: { res } });
  return {
    accepted: res.accepted,
    rejected: res.rejected,
    response: res.response,
  };
};
```

## Email service singleton (TypeScript)

**services/sendgrid/index.ts:**

```typescript
import sgMail from "@sendgrid/mail";
import type { MailDataRequired } from "@sendgrid/mail";

export interface SendEmailOptions {
  to: string | string[];
  subject: string;
  from?: { email: string; name?: string };
  html: string;
  text?: string;
  replyTo?: string;
  cc?: string | string[];
  bcc?: string | string[];
  attachments?: Array<{
    filename: string;
    content: string; // base64 encoded
    type?: string;
    disposition?: string;
  }>;
  categories?: string[];
  customArgs?: Record<string, string>;
  calendarContent?: string; // iCal content for auto-recognition
}

export interface SendGridResponse {
  success: boolean;
  message?: string;
  data?: any;
}

export class SendGridService {
  private static instance: SendGridService;
  private apiKey: string;
  private defaultFrom: { email: string; name?: string };

  constructor() {
    this.apiKey = process.env.SENDGRID_API_KEY || "";
    const emailProvider = (process.env.EMAIL_PROVIDER || "sendgrid").toLowerCase().trim();
    const isDevelopment = process.env.NODE_ENV === "development";
    const disableSendGrid = process.env.DISABLE_SENDGRID === "true";

    if (emailProvider === "sendgrid" && !this.apiKey && !isDevelopment && !disableSendGrid) {
      throw new Error("SENDGRID_API_KEY environment variable is required when EMAIL_PROVIDER=sendgrid");
    }

    if (this.apiKey) {
      sgMail.setApiKey(this.apiKey);
      console.log("[SendGrid] API key configured");
    } else if (emailProvider === "sendgrid" && (isDevelopment || disableSendGrid)) {
      console.warn("SendGrid API key not set - emails will be logged to console in development");
    } else if (emailProvider !== "sendgrid") {
      console.log(`[SendGrid] Not the selected provider (using ${emailProvider})`);
    }

    this.defaultFrom = {
      email: process.env.EMAIL_FROM_EMAIL || process.env.SENDGRID_FROM_EMAIL || "",
      name: process.env.EMAIL_FROM_NAME || process.env.SENDGRID_FROM_NAME || "",
    };

    if (emailProvider === "sendgrid" && !this.defaultFrom.email && !isDevelopment && !disableSendGrid) {
      throw new Error("EMAIL_FROM_EMAIL environment variable is required when EMAIL_PROVIDER=sendgrid");
    }
  }

  public static getInstance(): SendGridService {
    if (!SendGridService.instance) {
      SendGridService.instance = new SendGridService();
    }
    return SendGridService.instance;
  }

  async sendEmail(options: SendEmailOptions): Promise<SendGridResponse> {
    const { to, subject, from, html, text, replyTo, cc, bcc, attachments, categories, customArgs, calendarContent } = options;

    if (!to || (Array.isArray(to) && to.length === 0)) {
      throw new Error("Recipient email is required");
    }

    const isDevelopment = process.env.NODE_ENV === "development";
    const disableSendGrid = process.env.DISABLE_SENDGRID === "true";
    
    if ((isDevelopment || disableSendGrid) && !this.apiKey) {
      console.log("📧 [DEV MODE] Email would be sent:");
      console.log("   To:", Array.isArray(to) ? to.join(", ") : to);
      console.log("   Subject:", subject);
      console.log("   From:", from || this.defaultFrom);
      console.log("   HTML Preview:", html.substring(0, 200) + "...");
      return { success: true, message: "Email logged (SendGrid not configured in development)" };
    }

    try {
      const content: Array<{ type: string; value: string }> = [];

      if (text) {
        content.push({ type: 'text/plain', value: text });
      }

      content.push({ type: 'text/html', value: html });

      // Add calendar content for Gmail/Outlook auto-recognition
      if (calendarContent) {
        content.push({
          type: 'text/calendar; method=REQUEST',
          value: calendarContent,
        });
      }

      const msg: MailDataRequired = {
        to: Array.isArray(to) ? to : [to],
        from: from || this.defaultFrom,
        subject,
        content,
      } as MailDataRequired;

      if (replyTo) msg.replyTo = replyTo;
      if (cc) msg.cc = Array.isArray(cc) ? cc : [cc];
      if (bcc) msg.bcc = Array.isArray(bcc) ? bcc : [bcc];
      if (attachments && attachments.length > 0) {
        msg.attachments = attachments.map((att) => ({
          content: att.content,
          filename: att.filename,
          type: att.type,
          disposition: att.disposition || "attachment",
        }));
      }
      if (categories && categories.length > 0) msg.categories = categories;
      if (customArgs) msg.customArgs = customArgs;

      const [response] = await sgMail.send(msg);
      console.log(`[SendGrid] Email sent successfully. Status code:`, response.statusCode);

      return {
        success: true,
        message: "Email sent successfully",
        data: { statusCode: response.statusCode, headers: response.headers },
      };
    } catch (error: any) {
      const errorMessage = error?.response?.body?.errors?.[0]?.message || error?.message || "Unknown error occurred";
      console.error("[SendGrid] API error:", errorMessage);
      return {
        success: false,
        message: `Failed to send email: ${errorMessage}`,
        data: error?.response?.body,
      };
    }
  }
}

export const sendGridService = SendGridService.getInstance();
```

## SMS service with E.164 formatting

**services/sms/sms.service.ts:**

```typescript
import axios, { AxiosInstance } from "axios";

export interface SmsResult {
  success: boolean;
  message?: string;
  data?: any;
}

export interface SmsConfig {
  username: string;
  password: string;
  senderId: string;
  dltEntityId: string;
  singleApiUrl: string;
  bulkApiUrl: string;
}

type SmsType = "otp" | "transaction" | "promotional";

const SMS_TYPE_MAP: Record<SmsType, string> = {
  otp: "O",
  transaction: "T",
  promotional: "P",
};

export class SmsService {
  private static instance: SmsService;
  private client: AxiosInstance;
  private config: SmsConfig;
  private isConfigured: boolean = false;

  constructor() {
    this.client = axios.create({ timeout: 30000 });

    this.config = {
      username: process.env.SMS_USERNAME?.trim() || "",
      password: process.env.SMS_PASSWORD?.trim() || "",
      senderId: process.env.SMS_SENDER_ID?.trim() || "",
      dltEntityId: process.env.SMS_DLT_ENTITY_ID?.trim() || "",
      singleApiUrl: process.env.SMS_SINGLE_API_URL?.trim() || "",
      bulkApiUrl: process.env.SMS_BULK_API_URL?.trim() || "",
    };

    const hasRequiredConfig = this.config.username && this.config.password && this.config.senderId && this.config.singleApiUrl;

    if (hasRequiredConfig) {
      this.isConfigured = true;
      console.log(`[SMS] Service configured (Sender: ${this.config.senderId})`);
    } else {
      console.warn("[SMS] Service not configured. Set SMS_* environment variables.");
    }
  }

  public static getInstance(): SmsService {
    if (!SmsService.instance) {
      SmsService.instance = new SmsService();
    }
    return SmsService.instance;
  }

  public isReady(): boolean {
    return this.isConfigured;
  }

  private formatPhoneNumber(phone: string, countryCode: string = "91"): { countryCode: string; phoneNumber: string; fullNumber: string } {
    let cleaned = phone.replace(/[^\d+]/g, "");

    if (cleaned.startsWith("+")) {
      cleaned = cleaned.substring(1);
    }

    if (cleaned.startsWith("0")) {
      cleaned = cleaned.substring(1);
    }

    if (cleaned.length === 10) {
      return {
        countryCode,
        phoneNumber: cleaned,
        fullNumber: countryCode + cleaned,
      };
    }

    if (cleaned.length > 10 && cleaned.startsWith(countryCode)) {
      return {
        countryCode,
        phoneNumber: cleaned.substring(countryCode.length),
        fullNumber: cleaned,
      };
    }

    return {
      countryCode,
      phoneNumber: cleaned,
      fullNumber: countryCode + cleaned,
    };
  }

  async sendSms(to: string, message: string, options: { templateId?: string; smsType?: SmsType; countryCode?: string } = {}): Promise<SmsResult> {
    if (!this.isConfigured) {
      console.error("[SMS] Service not configured");
      return { success: false, message: "SMS service not configured" };
    }

    const { templateId, smsType = "transaction", countryCode = "91" } = options;
    const formatted = this.formatPhoneNumber(to, countryCode);

    const payload = {
      username: this.config.username,
      password: this.config.password,
      sender_id: this.config.senderId,
      body: message,
      to: formatted.fullNumber,
      dlt_template_id: templateId || "",
      sms_type: SMS_TYPE_MAP[smsType],
      sms_content_type: "Static",
      dlt_entity_id: this.config.dltEntityId,
      sms_encoding_type: "PL",
    };

    try {
      console.log(`[SMS] Sending SMS to ${formatted.fullNumber}`);
      const response = await this.client.post(this.config.singleApiUrl, payload, {
        headers: { "Content-Type": "application/json" },
      });

      console.log(`[SMS] SMS sent successfully`, response.data);
      return { success: true, data: response.data };
    } catch (error: any) {
      console.error("[SMS] Failed to send SMS:", error.message);
      return { success: false, message: error.message || "Failed to send SMS", data: error.response?.data };
    }
  }

  async sendOtp(phone: string, code: string, purpose: string = "verification"): Promise<boolean> {
    const message = `Your ${purpose} code is: ${code}. This code expires in 10 minutes. Do not share this code.`;
    const result = await this.sendSms(phone, message, { smsType: "otp" });
    return result.success;
  }
}

export const smsService = SmsService.getInstance();
```

## Notification service with preferences

**services/notifications/notifications.service.ts:**

```typescript
import { PrismaClient } from '@prisma/client';
import { SendGridService } from '../sendgrid/index.js';
import { verificationOtpEmail, passwordResetOtpEmail, welcomeEmail, interviewScheduledEmail } from './email-templates.js';

const sendGridService = SendGridService.getInstance();

export type NotificationType =
  | 'APPLICATION_UPDATE'
  | 'INTERVIEW_SCHEDULED'
  | 'INTERVIEW_REMINDER'
  | 'OFFER_RECEIVED'
  | 'OFFER_EXPIRING'
  | 'NEW_MESSAGE'
  | 'WELCOME'
  | 'VERIFICATION_OTP'
  | 'PASSWORD_RESET_OTP';

const notificationPreferenceMap: Record<NotificationType, string | null> = {
  APPLICATION_UPDATE: 'applicationUpdates',
  INTERVIEW_SCHEDULED: 'interviewScheduled',
  INTERVIEW_REMINDER: 'interviewScheduled',
  OFFER_RECEIVED: 'offerReceived',
  OFFER_EXPIRING: 'offerReminders',
  NEW_MESSAGE: 'recruiterMessages',
  WELCOME: null, // Always send
  VERIFICATION_OTP: null, // Always send
  PASSWORD_RESET_OTP: null, // Always send
};

async function isNotificationEnabled(
  prisma: PrismaClient,
  userId: string,
  notificationType: NotificationType
): Promise<boolean> {
  const prefField = notificationPreferenceMap[notificationType];

  if (prefField === null) {
    return true;
  }

  const prefs = await prisma.notificationPrefs.findUnique({ where: { userId } });

  if (!prefs) {
    return true;
  }

  return (prefs as Record<string, unknown>)[prefField] === true;
}

export async function sendNotification(
  prisma: PrismaClient,
  payload: { userId: string; type: NotificationType; data: Record<string, unknown> }
): Promise<boolean> {
  const { userId, type, data } = payload;

  try {
    const user = await prisma.user.findUnique({ where: { id: userId } });

    if (!user) {
      console.error(`[Notifications] User not found: ${userId}`);
      return false;
    }

    const isEnabled = await isNotificationEnabled(prisma, userId, type);
    if (!isEnabled) {
      console.log(`[Notifications] ${type} is disabled for user ${userId}`);
      return false;
    }

    let emailTemplate;
    switch (type) {
      case 'VERIFICATION_OTP':
        emailTemplate = verificationOtpEmail(user.name, data.otp as string);
        break;
      case 'PASSWORD_RESET_OTP':
        emailTemplate = passwordResetOtpEmail(user.name, data.otp as string);
        break;
      case 'WELCOME':
        emailTemplate = welcomeEmail(user.name);
        break;
      case 'INTERVIEW_SCHEDULED':
        emailTemplate = interviewScheduledEmail(data as any);
        break;
      default:
        console.error(`[Notifications] Unknown notification type: ${type}`);
        return false;
    }

    const result = await sendGridService.sendEmail({
      to: user.email,
      subject: emailTemplate.subject,
      html: emailTemplate.html,
      text: emailTemplate.text,
    });

    if (result.success) {
      console.log(`[Notifications] Sent ${type} notification to ${user.email}`);
    } else {
      console.error(`[Notifications] Failed to send ${type} notification to ${user.email}: ${result.message}`);
    }

    return result.success;
  } catch (error) {
    console.error(`[Notifications] Error sending notification:`, error);
    return false;
  }
}
```

## OTP flow with Redis

**services/auth/email.helper.js:**

```javascript
const { v4: uuid } = require('uuid');
const path = require('path');
const config = require('../../../config');
const logger = require('../../common/winston')('email-helpers');
const { retryOnFailure } = require('../../common/util/retrier.util');
const { getRedis } = require('../redis.init');
const emailProvider = require('../../common/email-provider');
const emailVerificationTemplate = require('../templates/emailVerificationLink');
const resetPasswordEmailTemplate = require('../templates/resetPasswordEmail');

const EMAIL_VERIFICATION_CODE_PREFIX = 'verify-email-';
const SET_PASS_CODE_PREFIX = 'set-pass-';

const redisReadWrite = getRedis();

const KEY_EXPIRY = {
  sendSetPasswordEmail: 30 * 24 * 60 * 60,
  sendEmailVerificationEmail: 30 * 24 * 60 * 60,
};

const sendSetPasswordEmail = async ({ user }) => {
  const { email, _id } = user;
  const resetCode = uuid();
  const key = `${SET_PASS_CODE_PREFIX}${resetCode}`;

  await redisReadWrite.set(key, JSON.stringify({ _id, email }), 'EX', KEY_EXPIRY.sendSetPasswordEmail);

  const url = `https://${path.join(config.app.host, '/auth/setPassword')}?code=${encodeURIComponent(resetCode)}`;

  if (config.app_env === 'development' && !config.sendEmailOnDev) {
    logger.info({ resetCode });
    return true;
  }
  return retryOnFailure(emailProvider.sendMail, config.get('emailProvider'), {
    email,
    subject: 'Password reset',
    bodyHtml: resetPasswordEmailTemplate.template({
      email,
      userName: user.firstName,
      resetLink: url,
      willExpireIn: parseInt(KEY_EXPIRY.sendSetPasswordEmail / (60 * 60 * 24), 10)
    })
  });
};

const sendEmailVerificationEmail = async (value, emailParams) => {
  const verificationCode = uuid();
  const { email, firstName } = emailParams;
  const key = `${EMAIL_VERIFICATION_CODE_PREFIX}${verificationCode}`;

  return redisReadWrite.set(key, value, 'EX', KEY_EXPIRY.sendEmailVerificationEmail).then(() => {
    const url = `https://${path.join(config.app.host, '/auth/emailVerification')}?code=${encodeURIComponent(verificationCode)}`;

    if (config.app_env === 'development' && !config.sendEmailOnDev) {
      logger.info({ verificationCode });
      return '';
    }

    return retryOnFailure(emailProvider.sendMail, config.get('emailProvider'), {
      email,
      subject: 'Registration confirmation',
      bodyHtml: emailVerificationTemplate({
        userName: firstName,
        verifyLink: url,
        willExpireIn: parseInt(KEY_EXPIRY.sendEmailVerificationEmail / (60 * 60 * 24), 10)
      })
    });
  });
};

const verifyEmailVerificationCode = async ({ code }) => {
  const key = `${EMAIL_VERIFICATION_CODE_PREFIX}${code}`;
  const userData = await redisReadWrite.get(key);
  
  if (!userData) {
    const err = new Error('Invalid code.');
    err.statusCode = 400;
    throw err;
  }

  await redisReadWrite.del(key);
  return JSON.parse(userData);
};

module.exports = {
  sendSetPasswordEmail,
  sendEmailVerificationEmail,
  verifyEmailVerificationCode,
};
```

---

**Note:** All snippets are genericized. Real service names, repo paths, company/org identifiers, infrastructure details (GCP projects, buckets, registries), and brand/tenant IDs have been removed or replaced with placeholders like `config.app.host`, `EMAIL_SENDER`, generic package names, and neutral service references ("the app", "myapp.com").
