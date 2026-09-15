# XobaMetrics

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
