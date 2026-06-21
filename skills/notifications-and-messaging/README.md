# notifications-and-messaging

Multi-provider notification delivery patterns for email and SMS, covering provider abstraction layers, auto-discovery, ENV-driven selection, fallback chains, template-driven messages, dev-mode logging, and E.164 phone formatting.

## What this skill covers

This skill encodes production patterns for building notification systems in Node.js/TypeScript applications, derived from real backend services handling transactional email (SendGrid, Nodemailer, AWS SES) and SMS (Twilio, vendor-specific APIs) delivery at scale.

**Core patterns:**

- **Provider abstraction**: common interface for email/SMS providers with per-provider adapters
- **Auto-discovery**: dynamic provider loading via directory scan
- **ENV-driven selection**: runtime provider switching via environment variables
- **Dev-mode logging**: local testing without API keys or quota burn
- **Template-driven messages**: reusable templates for OTP, verification, reminders, calendar invites
- **E.164 phone formatting**: international SMS delivery via standardized phone number format
- **Notification preferences**: opt-in/opt-out management with always-send overrides for critical messages
- **iCal/ICS calendar invites**: embedded calendar events in emails for auto-recognition by Gmail/Outlook
- **Retry and fallback**: graceful degradation via provider fallback chains
- **Cron-based reminders**: scheduled notifications for interviews, offer expiries, etc.

**Where it fits:**

- Distinct from `auth-and-rbac` (which generates OTP codes but delegates delivery to this layer)
- Distinct from `observability-and-logging` (this layer *uses* structured logging for notification telemetry)
- Complements `fastapi-service-patterns` or Express/Koa backends by providing the notification delivery layer

## Provenance

Patterns extracted from production Node.js/TypeScript backend services handling:

- User verification emails (OTP-based)
- Interview scheduling with calendar invites
- SMS-based login and phone verification
- Multi-provider email delivery with fallback
- Preference-aware notification dispatch
- Bulk email/SMS campaigns
- Dev-mode testing without live API calls

All examples are genericized for public use — no internal service names, credentials, or infrastructure details.

## When to use this skill

Invoke when:

- Building a new notification system or messaging layer
- Integrating SendGrid, Nodemailer, AWS SES, Twilio, or similar providers
- Implementing OTP delivery via email or SMS
- Sending calendar invites for meetings or interviews
- Adding notification preferences and opt-out management
- Creating a provider-agnostic abstraction layer for vendor switching
- Setting up dev-mode logging for local testing
- Implementing retry/fallback for high availability

## Structure

- `SKILL.md` — the full pattern guide (15 core conventions, skeleton examples, anti-patterns)
- `references/provider-abstraction.md` — auto-discovery, singletons, ENV-driven selection
- `references/templates-and-fallback.md` — template functions, iCal generation, OTP flows, retry patterns
- `references/repo-evidence.md` — genericized snippets from real services (short, no internal identifiers)
