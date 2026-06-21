# Provider Abstraction

Multi-provider email/SMS delivery with auto-discovery, ENV-driven selection, and singleton pattern.

## Auto-discovery pattern

Dynamically load provider modules from a directory:

```javascript
// app/common/email-provider/index.js
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

// Dispatcher: routes to the selected provider
exports.sendMail = (provider, emailContent) => providers[provider].sendMail(emailContent);
```

**Benefits:**

- Add new providers by dropping a `newprovider.provider.js` file into the directory
- No manual registration or config file edits
- Consistent interface across all providers

## Provider implementations

### SendGrid provider

```javascript
// app/common/email-provider/sendgrid.provider.js
const sgMail = require('@sendgrid/mail');
const config = require('../../../config');

if (config.emailProvider === 'sendgrid') {
  sgMail.setApiKey(config.sendGrid.apiKey);
}

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

### Nodemailer SMTP provider

```javascript
// app/common/email-provider/smtp.provider.js
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

## Singleton pattern (TypeScript)

```typescript
// services/sendgrid/index.ts
export class SendGridService {
  private static instance: SendGridService;
  private apiKey: string;
  private defaultFrom: { email: string; name?: string };

  constructor() {
    this.apiKey = process.env.SENDGRID_API_KEY || "";
    const emailProvider = (process.env.EMAIL_PROVIDER || "sendgrid").toLowerCase().trim();
    const isDevelopment = process.env.NODE_ENV === "development";

    if (emailProvider === "sendgrid" && !this.apiKey && !isDevelopment) {
      throw new Error("SENDGRID_API_KEY environment variable is required");
    }

    if (this.apiKey) {
      sgMail.setApiKey(this.apiKey);
      console.log("[SendGrid] API key configured");
    } else if (isDevelopment) {
      console.warn("[SendGrid] API key not set - emails will be logged to console in development");
    }

    this.defaultFrom = {
      email: process.env.EMAIL_FROM_EMAIL || "",
      name: process.env.EMAIL_FROM_NAME || "",
    };
  }

  public static getInstance(): SendGridService {
    if (!SendGridService.instance) {
      SendGridService.instance = new SendGridService();
    }
    return SendGridService.instance;
  }

  async sendEmail(options: SendEmailOptions): Promise<SendGridResponse> {
    const isDevelopment = process.env.NODE_ENV === "development";
    
    if (isDevelopment && !this.apiKey) {
      console.log("📧 [DEV MODE] Email would be sent:");
      console.log("   To:", options.to);
      console.log("   Subject:", options.subject);
      console.log("   HTML Preview:", options.html.substring(0, 200) + "...");
      return {
        success: true,
        message: "Email logged (SendGrid not configured in development)",
      };
    }

    try {
      const msg = {
        to: Array.isArray(options.to) ? options.to : [options.to],
        from: options.from || this.defaultFrom,
        subject: options.subject,
        html: options.html,
        text: options.text,
      };

      const [response] = await sgMail.send(msg);
      console.log(`[SendGrid] Email sent successfully. Status code:`, response.statusCode);

      return {
        success: true,
        message: "Email sent successfully",
        data: {
          statusCode: response.statusCode,
          headers: response.headers,
        },
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

**Key patterns:**

- Private constructor prevents direct instantiation
- `getInstance()` ensures single instance per process
- ENV check in constructor: throw in production, warn in dev
- Dev-mode fallback: log instead of send when API key missing
- Structured response: `{ success: boolean, message?: string, data?: any }`

## ENV-driven provider selection

```typescript
// services/email/index.ts
export type EmailProvider = "sendgrid" | "smtp" | "ses";

export class EmailService {
  private static instance: EmailService;
  private sendGridService: SendGridService;
  private smtpService: SmtpService;
  private sesService: SESService;
  private defaultProvider: EmailProvider;

  constructor() {
    this.sendGridService = SendGridService.getInstance();
    this.smtpService = SmtpService.getInstance();
    this.sesService = SESService.getInstance();

    const providerEnv = process.env.EMAIL_PROVIDER?.toLowerCase().trim();
    if (providerEnv === "smtp") {
      this.defaultProvider = "smtp";
    } else if (providerEnv === "ses") {
      this.defaultProvider = "ses";
    } else {
      this.defaultProvider = "sendgrid";
    }

    console.log(`[Email] Default provider: ${this.defaultProvider}`);
  }

  public static getInstance(): EmailService {
    if (!EmailService.instance) {
      EmailService.instance = new EmailService();
    }
    return EmailService.instance;
  }

  async sendEmail(options: EmailOptions, provider?: EmailProvider): Promise<EmailResponse> {
    const selectedProvider = provider || this.defaultProvider;

    switch (selectedProvider) {
      case "sendgrid":
        return this.sendGridService.sendEmail(options);
      case "smtp":
        return this.smtpService.sendEmail(options);
      case "ses":
        return this.sesService.sendEmail(options);
      default:
        throw new Error(`Unknown email provider: ${selectedProvider}`);
    }
  }
}
```

**Runtime override:**

```typescript
// Use default provider from ENV
await emailService.sendEmail({ to: 'user@example.com', subject: 'Hello', html: '<p>World</p>' });

// Force a specific provider
await emailService.sendEmail({ to: 'user@example.com', subject: 'Hello', html: '<p>World</p>' }, 'ses');
```

## SMS service singleton with configuration check

```typescript
// services/sms/sms.service.ts
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
      apiUrl: process.env.SMS_API_URL?.trim() || "",
    };

    const hasRequiredConfig = this.config.username && this.config.password && this.config.senderId && this.config.apiUrl;

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

  async sendSms(to: string, message: string): Promise<SmsResult> {
    if (!this.isConfigured) {
      console.error("[SMS] Service not configured");
      return { success: false, message: "SMS service not configured" };
    }

    try {
      const response = await this.client.post(this.config.apiUrl, {
        username: this.config.username,
        password: this.config.password,
        sender_id: this.config.senderId,
        body: message,
        to: to,
      });

      console.log(`[SMS] SMS sent successfully to ${to}`);
      return { success: true, data: response.data };
    } catch (error: any) {
      console.error("[SMS] Failed to send SMS:", error.message);
      return { success: false, message: error.message };
    }
  }
}

export const smsService = SmsService.getInstance();
```

**Key features:**

- `isReady()` method to check configuration before sending
- Graceful degradation: warn on startup, return error on send attempt
- No crashes in dev when SMS not configured
