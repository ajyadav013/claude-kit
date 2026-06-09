---
name: security-verification
description: Verify and enforce input sanitization and security best practices across all user input surfaces — forms, textareas, query params, URL params, and external data, for any web stack.
argument-hint: [component, page, or "all"]
disable-model-invocation: true
---

Run security verification on: $ARGUMENTS.

## Steps

1. **Identify all input surfaces**: Search the target code for every point where user input enters the application.

   ### Input Sources to Check
   Adjust patterns to match your project's framework/language:
   ```bash
   # Search for all input surfaces (examples for web frontends)
   grep -rn '<Input\|<input\|<textarea\|<Textarea' src/
   grep -rn 'useForm\|useSearchParams\|useParams\|queryParam' src/  # React/React Router
   grep -rn 'params\|request.args\|request.form' .  # Flask/Django/FastAPI
   grep -rn 'dangerouslySetInnerHTML\|innerHTML\|outerHTML' src/
   grep -rn 'window.location\|document.cookie\|localStorage\|sessionStorage' src/
   grep -rn 'eval\|new Function\|document.write' src/
   ```

2. **Audit each input source against the checklist**:

   ### Form Inputs (`<input>`, `<Input>`, or framework equivalents)
   | Check | Status | Fix |
   |-------|--------|-----|
   | Schema validation on submit (Zod/Joi/Yup/Pydantic/etc.) | | Add validation schema with `.trim().min(1)` or equivalent |
   | `maxLength` attribute/constraint set | | Add length limit |
   | HTML entities escaped (auto in most modern frameworks) | | Verify template engine auto-escapes |
   | No raw value used in `href` or `src` | | Validate URL format before use |
   | Input type matches expected data | | Use semantic types (email, number, etc.) |

   ### Textareas (multi-line input fields)
   | Check | Status | Fix |
   |-------|--------|-----|
   | Schema validation on submit with max length | | Add `.trim().max(N)` or equivalent |
   | `maxLength` attribute/constraint set | | Add length limit |
   | Content not rendered as raw HTML | | Use text rendering, never HTML injection |

   ### Form Submissions (validation libraries: react-hook-form, Formik, WTForms, etc.)
   | Check | Status | Fix |
   |-------|--------|-----|
   | Schema validation attached to form handler | | Add validator integration |
   | All fields validated before processing | | Use framework's validation wrapper |
   | Error messages shown for invalid input | | Display validation errors to user |
   | Submit button disabled during submission | | Use framework's submission state |

   ### URL Query Parameters (framework routing/request parsing)
   | Check | Status | Fix |
   |-------|--------|-----|
   | Parsed with safe API (URLSearchParams, framework request parsers) | | Never parse `window.location` or raw query strings manually |
   | Values validated/cast before use | | Coerce to expected type with validation |
   | Default values for missing params | | Use `.get('key', default)` or equivalent |
   | Not used in `href`/`src` without validation | | Validate URL format |

   ### URL Path Parameters (framework routing)
   | Check | Status | Fix |
   |-------|--------|-----|
   | Type-checked after extraction | | Cast/validate params after extraction |
   | Validated against expected pattern | | Check format/range before use |
   | Not interpolated into URLs unsafely | | Use URL encoding (encodeURIComponent or equivalent) |

   ### Dangerous Patterns (universal across web stacks)
   | Pattern | Risk | Fix |
   |---------|------|-----|
   | `dangerouslySetInnerHTML` (React), `{% autoescape off %}` (Jinja), `{!! $var !!}` (Blade) | XSS | Remove or sanitize with DOMPurify/bleach/equivalent |
   | `innerHTML` / `outerHTML` | XSS | Use framework's safe template rendering |
   | `document.write` | XSS | Never use |
   | `eval()` / `new Function()` / `exec()` / `system()` | Code injection | Never use with user input |
   | `window.location = userInput` | Open redirect | Validate against allowlist |
   | Template literals in `href` without validation | XSS via `javascript:` protocol | Validate URL scheme |

3. **Check for OWASP Top 10 frontend/API concerns**:

   | # | Vulnerability | Check |
   |---|--------------|----------------|
   | A03 | Injection (XSS, SQL, Command) | No raw HTML rendering of user input; parameterized queries; no shell command interpolation |
   | A05 | Security Misconfiguration | No secrets in client-side code or version control |
   | A07 | Cross-Site Scripting | All outputs escaped, no unsafe HTML injection |
   | A08 | Software Integrity | Dependencies from trusted sources, audit tools clean (npm audit, pip-audit, etc.) |
   | A09 | Logging Failures | No sensitive data in logs (passwords, tokens, PII) |

4. **Verify sanitization utilities exist**: Check the project's utility module for sanitization helpers. If missing, add stack-appropriate versions:

   **Example (TypeScript/JavaScript):**
   ```typescript
   // Sanitize user input for display
   export function sanitizeInput(input: string): string {
     return input.trim().replace(/[<>]/g, '');
   }

   // Validate URL is safe (no javascript: protocol)
   export function isSafeUrl(url: string): boolean {
     try {
       const parsed = new URL(url, window.location.origin);
       return ['http:', 'https:'].includes(parsed.protocol);
     } catch {
       return false;
     }
   }

   // Encode value for URL parameter
   export function safeParam(value: string): string {
     return encodeURIComponent(value.trim());
   }
   ```

   **Example (Python):**
   ```python
   from urllib.parse import urlparse, quote
   from bleach import clean

   def sanitize_input(input: str) -> str:
       return clean(input.strip(), tags=[], strip=True)

   def is_safe_url(url: str) -> bool:
       try:
           parsed = urlparse(url)
           return parsed.scheme in {'http', 'https'}
       except Exception:
           return False

   def safe_param(value: str) -> str:
       return quote(value.strip(), safe='')
   ```

5. **Report findings**: Output a security audit table:

   | File | Line | Input Source | Vulnerability | Severity | Fix |
   |------|------|-------------|---------------|----------|-----|

   Severity levels:
   - **Critical**: Direct XSS vector or code injection
   - **High**: Missing validation on user input that affects application state
   - **Medium**: Missing sanitization on display-only input
   - **Low**: Missing length limit or type attribute

6. **Apply fixes**: For each finding, apply the recommended fix. Prioritize Critical and High first.

7. **Verify**: Run the project's linter, type checker, and build to confirm the changes are valid.

## Quick Reference: Secure Input Pattern (React + Zod example)

```tsx
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Input } from '@/components/ui';

const schema = z.object({
  name: z.string().trim().min(1, 'Name is required').max(100),
  email: z.string().trim().email('Invalid email').max(255),
  notes: z.string().trim().max(1000).optional(),
});

type FormData = z.infer<typeof schema>;

function SecureForm() {
  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<FormData>({
    resolver: zodResolver(schema),
  });

  const onSubmit = (data: FormData) => {
    // data is validated and typed — safe to use
  };

  return (
    <form onSubmit={handleSubmit(onSubmit)}>
      <Input {...register('name')} maxLength={100} />
      {errors.name && <p className="text-sm text-red-600">{errors.name.message}</p>}

      <Input {...register('email')} type="email" maxLength={255} />
      {errors.email && <p className="text-sm text-red-600">{errors.email.message}</p>}

      <textarea {...register('notes')} maxLength={1000} />
      {errors.notes && <p className="text-sm text-red-600">{errors.notes.message}</p>}

      <button type="submit" disabled={isSubmitting}>Submit</button>
    </form>
  );
}
```

## Quick Reference: Secure Input Pattern (Python/FastAPI + Pydantic example)

```python
from pydantic import BaseModel, EmailStr, Field

class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: EmailStr = Field(max_length=255)
    notes: str | None = Field(None, max_length=1000)

@router.post("/users", response_model=UserRead, status_code=201)
async def create_user(payload: UserCreate) -> UserRead:
    # payload is validated and typed — safe to use
    # Pydantic auto-trims and validates
    ...
```

## References

- OWASP Top 10: https://owasp.org/www-project-top-ten/
- OWASP XSS Prevention Cheat Sheet: https://cheatsheetseries.owasp.org/cheatsheets/Cross_Site_Scripting_Prevention_Cheat_Sheet.html
- Validation libraries: Zod (TS/JS), Joi (JS), Pydantic (Python), WTForms (Python), Bean Validation (Java)
