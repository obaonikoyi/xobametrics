# XobaMetrics

> ## Status: paused — September 2026
>
> **Paused to concentrate on two other projects — not because the hard parts
> are missing. They are built.** An earlier version of this note said real
> platform OAuth was never implemented. That was wrong: it repeated a stale
> line from the PRD instead of reading the code.
>
> ### What is actually built
>
> - **Google/YouTube OAuth 2.0** (`backend/youtube.py`, 615 lines): auth, token
>   and revoke endpoints, scope checking for `youtube.readonly` and
>   `yt-analytics.readonly`, refresh tokens encrypted at rest with Fernet, and a
>   background historical import that runs after the callback without delaying
>   Google's redirect
> - **SoundCloud OAuth 2.1** (`backend/soundcloud.py`, 608 lines): authorization
>   code flow with PKCE S256, single-use refresh tokens, URNs as stable ids
> - **Sign in with Google** (`backend/google_auth.py`): OpenID Connect with
>   PKCE; the ID token's signature, issuer, audience, expiry and nonce are
>   checked here, and the login is bound to the browser tab that started it.
>   A Google identity never takes over a password account by email: password
>   users link Google from the account menu. See
>   [setting it up](docs/DEPLOYMENT.md#sign-in-with-google).
> - Email/password auth with JWT and brute-force lockout, CSV import, the
>   Day-0 "Release Race" comparison, reports, and a grounded AI panel
> - ~4,100 lines of Python and ~6,000 of JavaScript, with 55 tests
>
> Both OAuth routers are registered in `server.py`; the frontend has the
> connection and callback pages.
>
> ### What is genuinely unfinished
>
> **The deployment.** `MONGO_URL` is not configured, and backend startup and
> readiness are unverified against the custom domain. `metrics.3xoba.com`
> serves the frontend; that confirms frontend delivery and nothing else.
> Full-stack sign-in, CSV import and AI have not been verified end to end in
> production.
>
> ### Builder-platform coupling, removed September 2026
>
> This project was scaffolded with the Emergent builder, which wired its own
> services into the code. All of them are gone, and nothing here needs
> Emergent to install, build or run:
>
> - **AI** called the model through a wrapper wheel served from the vendor's
>   CDN rather than PyPI. It now goes through `backend/ai_provider.py`, an
>   interface with an OpenAI implementation (`OPENAI_API_KEY`, `AI_MODEL`).
> - **CSV archiving** sent every upload to the vendor's object store. It now
>   writes to a directory set by `UPLOAD_ARCHIVE_DIR`; unset means uploads are
>   not archived, and imports still work.
> - **"Continue with Google"** asked `demobackend.emergentagent.com` whose a
>   session was and signed in whatever email came back, with nothing verified
>   locally. The button, callback page and `POST /api/auth/session` are
>   removed, and replaced by a real Google sign-in in `backend/google_auth.py`
>   that verifies Google's ID token itself.
> - **The frontend page** loaded the vendor's script and sent PostHog
>   analytics, with session recording, to the vendor's host under the
>   vendor's project key. Both are removed.
> - **Build tooling**: the vendor's editor overlay and visual-edits packages
>   (downloaded from its CDN), the preview health-check plugin, and the
>   backend's ~130-package template requirements are replaced by the 15
>   direct dependencies the backend imports (`requirements-dev.txt` adds the
>   test tools).
> - **Repository leftovers**: cron scripts, markers, git identity, agent test
>   reports and playbooks are removed, and `.emergent/` is gitignored.
>   `docs/PRD.md` was kept as a real product document and marked where stale.
>
> ### Honest note on stored data
>
> The previous synthetic sync worker is disabled and old snapshots need
> provenance review. Demo data is not live analytics. Nothing in this
> repository should be read as real measurement.

A creator analytics dashboard with a React/CRACO frontend, FastAPI backend and MongoDB database. It groups content into releases and compares stored observations by release age (Day 0 is the original release date).

**Frontend address:** `https://metrics.3xoba.com` — verified to return the Vercel frontend over HTTPS on 15 September 2026. This confirms frontend delivery, not working sign-in or live analytics.

## Current deployment status — 15 September 2026

The existing Railway `xobametrics` service now builds from `/backend`, starts with `uvicorn server:app --host 0.0.0.0 --port "$PORT" --workers 1`, and checks `/api/ready`. `FRONTEND_URL`, explicit `CORS_ORIGINS`, `DB_NAME`, and `JWT_SECRET` are configured on that service. Scheduled sync and automatic demo seeding remain disabled. Secret values are stored outside the repository.

**Still required:** connect a dedicated MongoDB database (`MONGO_URL` is not configured), verify backend startup/readiness, then configure the frontend's `REACT_APP_BACKEND_URL` and redeploy. AI also needs backend-side `OPENAI_API_KEY` and `AI_MODEL`. No new database or paid infrastructure was provisioned during this configuration step. No existing data was migrated or deleted. Full-stack sign-in, CSV import, and AI have not yet been verified on the custom domain.

## Read this before deployment

The frontend builds on Vercel. Real platform OAuth/sync is **not implemented**; CSV is the current import path. Demo data is not live analytics. The previous synthetic sync worker has been disabled; old snapshots require provenance review. The AI explains supplied backend results, but its responses do not yet have automated numeric validation.

See [deployment instructions and launch checklist](docs/DEPLOYMENT.md) for backend hosting, environment variables, custom DNS, acceptance tests and the next priorities. The status above supersedes the checklist's earlier notes about an unattached custom domain or absent Railway service.

Frontend: `cd frontend`, install dependencies using the project's package-manager configuration, then `yarn start` or `yarn build`. Backend: configure the environment privately, install `backend/requirements.txt`, then from `backend` run `uvicorn server:app --host 0.0.0.0 --port 8000`. Full end-to-end deployment still requires verification.

## Focused regression tests

```sh
node --test frontend/tests/api-config.test.mjs
python -m unittest discover -s backend/tests -p 'test_launch_safety_unit.py'
python -m unittest discover -s backend/tests -p 'test_google_auth.py'
```

These are isolated unit tests, not substitutes for database, OAuth and browser tests.
