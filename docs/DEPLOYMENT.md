# XobaMetrics: deployment and launch checklist

## Status and scope — 15 September 2026

The React/CRACO frontend builds on Vercel. This is not yet proof of a functioning full-stack production app. At review time, Vercel listed `xobametrics-gamma.vercel.app` and preview aliases, but not `metrics.3xoba.com`. Its `/api/auth/me` returned the frontend HTML, not a JSON API response. No XobaMetrics backend service was found in the connected Railway account.

Keep the implemented React + FastAPI + MongoDB stack. Do not rewrite it just for deployment. This patch stops simulated platform sync, blocks fake connect/reconnect success, guards the AI focus-release scope, preserves CSV rows beyond the preview, and makes missing backend configuration visible. It does not implement OAuth, create a database, attach DNS, or migrate production data.

## 1. Attach the custom domain

In Vercel, select **xobametrics → Settings → Domains → Add Domain**, then enter `metrics.3xoba.com`. Attach it to production rather than redirecting it to a different site.

Copy the exact DNS record Vercel displays. A subdomain normally requires a CNAME with host/name `metrics`; the target is project-specific. Add or correct only that record at the authoritative DNS provider. Do not change the apex domain, move nameservers, or alter other Xoba applications. If Vercel manages the DNS, follow its automatic configuration flow. Wait for domain verification and an HTTPS certificate; then test the address.

The current connected Vercel tools provide project/deployment inspection but no domain-attachment or DNS-write action. That account-side step is not completed by committing this repository.

Official instructions: https://vercel.com/docs/domains/working-with-domains/add-a-domain

## 2. Establish the production backend

Provision a dedicated FastAPI service (for example Railway) with a production MongoDB database after approving the hosting cost and data-migration plan. Do not reuse another application's database.

Use `backend` as the service root. The start command for a persistent Python service is:

```sh
uvicorn server:app --host 0.0.0.0 --port "$PORT" --workers 1
```

Install from `backend/requirements.txt` in a clean build. It lists only the backend's direct dependencies, all from PyPI; `backend/requirements-dev.txt` adds the test tools.

Copy variable names from `backend/.env.example`. Store real values in the backend host's secret/environment controls, never in GitHub, public files, screenshots or chat. Requirements include `MONGO_URL`, `DB_NAME`, `JWT_SECRET`, and the exact allowed frontend origins. `OPENAI_API_KEY` and `AI_MODEL` are needed for the AI panel. Confirm your key can call the chosen model. A model name in source is not verification of provider availability.

Leave `ENABLE_SCHEDULED_SYNC=false` and `ENABLE_DEMO_SEED=false`. No adapter currently fetches platform metrics. Enabling the scheduler only schedules a safe no-op; it does not enable OAuth. Use one application worker until proper distributed job locking is implemented. Rotate any sample administrator password previously shared or used during testing. Existing passwords are not reset by a restart.

Back up any existing database before migration. Review old snapshots: the previous worker could add synthetic growth to ordinary connected accounts, including CSV-imported content. Historical provenance was not recorded reliably, so do not blindly delete records or assume every old snapshot is real. Preserve originals, quarantine suspect data, and reimport authoritative exports where appropriate. This patch does not modify or delete existing stored data.

## 3. Connect Vercel to the API

Retain these frontend settings:

| Setting | Value |
| --- | --- |
| Root directory | `frontend` |
| Framework | Create React App |
| Build command | `yarn build` |
| Output directory | `build` |

Set `REACT_APP_BACKEND_URL` in Vercel to the actual HTTPS backend origin, with no `/api` suffix or credentials. This variable is public, compiled into the frontend. Never put MongoDB credentials, OAuth client secrets or AI keys in a `REACT_APP_` variable. Redeploy after setting it. Until configured, the frontend deliberately shows a setup notice rather than sending requests to `undefined/api`.

The backend `FRONTEND_URL` should be `https://metrics.3xoba.com`. Its `CORS_ORIGINS` may temporarily include the verified Vercel production alias. Do not use `*` with authenticated requests. Verify cookie/Bearer behaviour on the final domain with a real test account. Sign-in is email and password only; Google sign-in has been removed until a real Google OAuth sign-in flow is built. Google sign-in is distinct from authorising access to a YouTube channel.

Official environment-variable guidance: https://vercel.com/docs/environment-variables

## 4. Acceptance tests before inviting users

* API `/api/health` returns JSON; `/api/ready` returns ready only when MongoDB responds.
* Signup/login, refresh, logout and profile switching work on the custom domain.
* One user cannot access another user's releases, reports or AI insights.
* A CSV with more than 50 rows keeps every permitted row; upload and commit counts match. Do not interpret daily counts as cumulative totals.
* Day 0 uses the actual release date, not the connection date or first available CSV observation. Missing history must remain unknown.
* Connections and sync do not claim API success before real adapters exist.
* AI and public report links are tested separately with controlled accounts. A successful build alone is insufficient.

## 5. Next development priorities

1. Complete domain, stable backend, database and frontend API configuration.
2. Fix remaining analytics semantics: daily versus cumulative imports; account-level followers versus content metrics; non-deduplicated views/plays versus unique reach; incomplete campaign observations and first-week coverage. Require explicit original publish dates on CSV imports.
3. Separate and label demo data throughout dashboards and reports. Add data provenance and a safe review process for historical synthetic snapshots.
4. Implement real YouTube OAuth, state/PKCE as appropriate, secure server-side token storage, channel/video discovery, metrics fetching and reconnect behaviour. Credentials alone do not implement these flows.
5. Add durable, idempotent observation storage and jobs with unique keys, UTC timestamps, locking, retries and rate-limit handling. Never fabricate missing history.
6. Add signup/AI/import/sync rate limits, AI budget controls, account deletion/disconnect, revocable reports, privacy notices, and automated response grounding checks. Prompt instructions alone do not guarantee factual AI output.
7. Run a small private beta with the founder's real catalogue, then add SoundCloud when its access and metrics have been verified. Defer more platforms and billing until the data is trustworthy.

## Local regression checks

```sh
node --test frontend/tests/api-config.test.mjs
python -m unittest discover -s backend/tests -p 'test_launch_safety_unit.py'
python -m compileall -q backend
```

The launch-safety tests isolate source functions with mocked dependencies; they do not connect to MongoDB or replace HTTP, OAuth, browser or production smoke tests. Older tests that expect stubbed connection success must be updated to the explicit unavailable contract.
