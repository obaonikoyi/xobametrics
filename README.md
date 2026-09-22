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
> ### Build-tool coupling, removed September 2026
>
> This project was scaffolded with the Emergent builder, which left two runtime
> dependencies on that vendor. Both are gone:
>
> - `ai.py` imported a chat wrapper from a wheel served off the vendor's
>   CloudFront bucket rather than PyPI — so the backend could not install at all
>   if that URL went away. It now calls the provider through `ai_provider.py`,
>   an interface with an OpenAI implementation, matching the rule this codebase's
>   sibling project already follows.
> - `storage.py` POSTed every uploaded CSV to the vendor's hosted object store.
>   It now writes to a directory this deployment controls, set by
>   `UPLOAD_ARCHIVE_DIR`. Unset means uploads are simply not archived; imports
>   still work, as they already did when the remote store failed.
>
> A third was found while doing this and is a security issue rather than
> coupling: `POST /api/auth/session` took a session id from the caller, asked
> `demobackend.emergentagent.com` whose it was, and signed in — or created — an
> account for whatever email came back, already beta approved, with no
> signature, issuer or audience verified locally. It is now **off unless
> `ENABLE_EMERGENT_GOOGLE_LOGIN=true`**, and the right fix is a real Google
> OAuth flow, which `youtube.py` already shows how to do.
>
> The vendor's committed cron scripts, git identity, agent test protocol and
> markers have been removed and gitignored. `docs/PRD.md` was kept — it is a
> real product document — and marked where it has gone stale.
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

The first Python install blocker was an unavailable PyPI package, `emergentintegrations`. `backend/requirements.txt` now points directly to its published versioned wheel. The duplicate LiteLLM direct requirement was removed because its hash-fragment URL conflicted with the URL declared by the Emergent wheel. Railway subsequently reported that the Python dependencies installed successfully.

**Still required:** connect a dedicated MongoDB database (`MONGO_URL` is not configured), verify backend startup/readiness, then configure the frontend's `REACT_APP_BACKEND_URL` and redeploy. AI also needs a valid backend-side `EMERGENT_LLM_KEY`. No new database or paid infrastructure was provisioned during this configuration step. No existing data was migrated or deleted. Full-stack sign-in, CSV import, and AI have not yet been verified on the custom domain.

## Read this before deployment

The frontend builds on Vercel. Real platform OAuth/sync is **not implemented**; CSV is the current import path. Demo data is not live analytics. The previous synthetic sync worker has been disabled; old snapshots require provenance review. The AI explains supplied backend results, but its responses do not yet have automated numeric validation.

See [deployment instructions and launch checklist](docs/DEPLOYMENT.md) for backend hosting, environment variables, custom DNS, acceptance tests and the next priorities. The status above supersedes the checklist's earlier notes about an unattached custom domain or absent Railway service.

Frontend: `cd frontend`, install dependencies using the project's package-manager configuration, then `yarn start` or `yarn build`. Backend: configure the environment privately, install `backend/requirements.txt`, then from `backend` run `uvicorn server:app --host 0.0.0.0 --port 8000`. Full end-to-end deployment still requires verification.

## Focused regression tests

```sh
node --test frontend/tests/api-config.test.mjs
python -m unittest discover -s backend/tests -p 'test_launch_safety_unit.py'
```

These are isolated unit tests, not substitutes for database, OAuth and browser tests.
