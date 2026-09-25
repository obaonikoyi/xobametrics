# XobaMetrics: deployment

| Part | Where | Address |
| --- | --- | --- |
| Frontend | Vercel project `xobametrics`, root `frontend`, Create React App | `https://xobametrics.com` (`www` redirects to it) |
| Backend | Railway project `fulfilling-encouragement`, service `xobametrics`, root `backend` | `https://api.xobametrics.com` |
| Database | Railway PostgreSQL service in the same project | private network only |

The old addresses (`metrics.3xoba.com`, `xobametrics-production.up.railway.app`)
keep working during the move.

## 1. Domain and DNS

`xobametrics.com` is registered with and served by Cloudflare. The domain is
already attached on both sides (Vercel: `xobametrics.com` and
`www.xobametrics.com`; Railway: `api.xobametrics.com`), and they verify on
their own once these records exist.

In Cloudflare → DNS → Records. Every record is **DNS only (grey cloud)**:
Vercel and Railway issue their own certificates, and the proxy gets in the way.

| Type | Name | Content |
| --- | --- | --- |
| A | `@` | `76.76.21.21` |
| CNAME | `www` | `cname.vercel-dns.com` |
| CNAME | `api` | `6lfzirog.up.railway.app` |

Remove any parking A/AAAA/CNAME records Cloudflare created on `@` or `www`.

### Email anti-spoofing

The domain neither sends nor receives email, so tell the world to reject any
that claims to be from it:

| Type | Name | Content |
| --- | --- | --- |
| TXT | `@` | `v=spf1 -all` |
| TXT | `_dmarc` | `v=DMARC1; p=reject; sp=reject; adkim=s; aspf=s` |
| TXT | `*._domainkey` | `v=DKIM1; p=` |
| MX | `@` | `.` priority `0` (null MX; skip if Cloudflare refuses it) |

When the product starts sending email (sign-up confirmation, password reset),
replace the SPF record with the provider's and add its DKIM keys; keep DMARC.
To receive email with Cloudflare Email Routing instead, drop the null MX.

Also: DNS → Settings → **Enable DNSSEC**. Optionally, once the site works, a
CAA record `@` `0 issue "letsencrypt.org"` limits certificates to the issuer
Vercel and Railway both use.

## 2. Database

The backend needs PostgreSQL 14 or newer; it creates its tables on start-up
from `backend/schema.sql`.

1. In the Railway project: **+ New → Database → PostgreSQL**.
2. On the `xobametrics` service set `DATABASE_URL=${{Postgres.DATABASE_URL}}`.
3. To bring the existing MongoDB data across, also set
   `MONGO_MIGRATION_URL=${{MongoDB.MONGO_URL}}` and
   `MONGO_MIGRATION_DB` to the old `DB_NAME` value.
4. Deploy. On start-up the backend copies everything in one transaction, but
   only while Postgres has no users, so a restart cannot copy twice or
   overwrite anything. The deploy log shows a line starting
   `Imported MongoDB data into Postgres` with the counts and every clean-up it
   made (duplicates folded, orphans skipped).
5. Check the site, then remove `MONGO_MIGRATION_URL`, `MONGO_MIGRATION_DB`,
   `MONGO_URL` and `DB_NAME`. Keep the MongoDB service for a week or two as a
   backup, then delete it. `pymongo` can then come out of
   `backend/requirements.txt` along with `backend/mongo_import.py`.

Everyone signs in again after this deploy: sessions are now stored in the
database, and older tokens do not name one.

## 3. Backend variables

Names and notes are in `backend/.env.example`. Store values only in Railway.

- `DATABASE_URL`, `JWT_SECRET` (long and random)
- `FRONTEND_URL=https://xobametrics.com`
- `CORS_ORIGINS=https://xobametrics.com,https://metrics.3xoba.com` (never `*`)
- `PUBLIC_API_URL=https://api.xobametrics.com`
- `ANTHROPIC_API_KEY` for the AI panel (Claude; key from console.anthropic.com).
  `AI_MODEL` is optional and overrides the default model
- `BETA_INVITE_CODES` — comma-separated; empty means open sign-up
- OAuth: `GOOGLE_*`, `YOUTUBE_*`, `SOUNDCLOUD_*` (redirect URIs on
  `https://api.xobametrics.com/...`, registered identically with each provider)
- `ENABLE_SCHEDULED_SYNC=true` to refresh connected platforms at 04:00 UTC;
  `ENABLE_DEMO_SEED=false`
- `ADMIN_EMAIL` / `ADMIN_PASSWORD` only to create a first admin; rotate any
  password that has ever been shared

Start command: `uvicorn server:app --host 0.0.0.0 --port "$PORT" --workers 1`
(one worker: the scheduler runs in-process). Health check: `/api/ready`.

## 4. Frontend variables

In Vercel set `REACT_APP_BACKEND_URL=https://api.xobametrics.com` (no `/api`,
no secrets — it is compiled into public JavaScript) and redeploy. Vercel
installs with the committed `yarn.lock`.

## 5. Sign in with Google

Optional: until it is configured the button is hidden and email/password works.

1. Google Cloud Console → **APIs & Services → OAuth consent screen**: app name,
   support email, authorised domain `xobametrics.com`, scopes `openid`, `email`,
   `profile` (none need Google verification).
2. **Credentials** → a **Web application** OAuth client (the YouTube one is
   fine). Under **Authorized redirect URIs** add
   `https://api.xobametrics.com/api/auth/google/callback`.
3. On Railway set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` (and
   `GOOGLE_REDIRECT_URI` only if the API address differs from
   `PUBLIC_API_URL`). Google returns people to `FRONTEND_URL` + `/auth/google`.
4. Redeploy. `/api/health` reports `google_signin_configured: true`.

A new Google user gets a new account (with an invite code when codes are set:
they enter it under **Create an account** before continuing with Google).
Someone whose email already has a password account is asked to sign in with
the password and choose **Connect Google sign-in** from the account menu —
deliberately, since sign-up does not verify email addresses.

## 6. Acceptance checks

- `/api/health` returns JSON; `/api/ready` returns ready.
- Sign up (with an invite code if set), sign out, sign in; after signing out
  the old session no longer works.
- A second account cannot see the first account's releases, reports or AI.
- CSV import: every row kept, dates must be `YYYY-MM-DD`, a repeated date
  keeps one row per day.
- Release Race uses the real release date as Day 0; missing days stay missing.
- Google sign-in: new account; password account refused by email then linked
  from the menu; sign-in again after linking.
- YouTube and SoundCloud connect, sync and disconnect with a real account.
- A public report link shows only the report.
