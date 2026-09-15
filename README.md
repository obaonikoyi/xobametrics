# XobaMetrics

A creator analytics dashboard with a React/CRACO frontend, FastAPI backend and MongoDB database. It groups content into releases and compares stored observations by release age (Day 0 is the original release date).

**Deployment target:** `metrics.3xoba.com` (custom domain verification pending at the September 2026 review).

## Read this before deployment

The frontend builds on Vercel. Real platform OAuth/sync is **not implemented**; CSV is the current import path. Demo data is not live analytics. The previous synthetic sync worker has been disabled; old snapshots require provenance review. The AI explains supplied backend results, but its responses do not yet have automated numeric validation.

See [deployment instructions and launch checklist](docs/DEPLOYMENT.md) for backend hosting, environment variables, custom DNS, acceptance tests and the next priorities.

Frontend: `cd frontend`, install dependencies using the project's package-manager configuration, then `yarn start` or `yarn build`. Backend: configure the environment privately, install `backend/requirements.txt`, then from `backend` run `uvicorn server:app --host 0.0.0.0 --port 8000`. External backend dependency installation and full end-to-end deployment still require verification.

## Focused regression tests

```sh
node --test frontend/tests/api-config.test.mjs
python -m unittest discover -s backend/tests -p 'test_launch_safety_unit.py'
```

These are isolated unit tests, not substitutes for database, OAuth and browser tests.
