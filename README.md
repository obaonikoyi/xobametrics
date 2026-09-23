# XobaMetrics

A creator analytics dashboard. It brings a musician's numbers together from
YouTube, SoundCloud and CSV exports, saves an observation every day, and lines
releases up from their release date ("Day 0") so they can be compared fairly —
the **Release Race**. An AI panel explains the results using only numbers the
backend has calculated.

React (CRACO) frontend on Vercel · FastAPI backend on Railway · PostgreSQL.

## Status — September 2026

Paused to concentrate on two other projects. The product is built; what is
left is putting it on its own domain and checking it end to end.

**Built**
- Email/password sign-in with server-side sessions (signing out ends the
  session) and brute-force lockout; optional invite codes for the private beta.
- Sign in with Google (`backend/google_auth.py`): OpenID Connect with PKCE,
  ID token verified on the server, login bound to the tab that started it. A
  Google identity never takes over a password account by email; password
  users link Google from the account menu.
- YouTube (`backend/youtube.py`, `youtube_history.py`) and SoundCloud
  (`backend/soundcloud.py`) OAuth, daily sync and YouTube history backfill;
  tokens encrypted at rest.
- CSV import, release organisation and cross-platform merge suggestions,
  Release Race, reports with public share links, and the grounded AI panel.

**To finish**
1. Point `xobametrics.com` at Vercel and `api.xobametrics.com` at Railway
   (records in [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md#1-domain-and-dns)).
2. Add a Postgres database on Railway and copy the old MongoDB data across
   ([how](docs/DEPLOYMENT.md#2-database)).
3. Set the AI and Google credentials, then run the acceptance checks.

Demo data is not live analytics, and snapshots written by the old synthetic
sync worker (since removed) should be reviewed before being trusted.

## History: the Emergent builder

The project was scaffolded with Emergent, which wired its own services into
the code: an AI wrapper downloaded from its CDN, CSV uploads sent to its
storage, a Google sign-in that trusted its demo server, PostHog analytics under
its key on every page, editor packages from its CDN, and MongoDB, the only
database it supports. All of it has been removed or replaced; nothing here
needs Emergent to install, build or run. `docs/PRD.md` is the original product
document, marked where it has gone stale.

## Running it locally

Backend (Python 3.11, PostgreSQL 14+):

```sh
cd backend
pip install -r requirements-dev.txt
cp .env.example .env   # set DATABASE_URL and JWT_SECRET at least
uvicorn server:app --reload --port 8000
```

The schema is created on start-up (`backend/schema.sql`).

Frontend (Node 20, Yarn 1):

```sh
cd frontend
yarn install --frozen-lockfile
REACT_APP_BACKEND_URL=http://localhost:8000 yarn start
```

## Tests

GitHub Actions runs everything on each pull request
(`.github/workflows/ci.yml`). Locally:

```sh
# backend: needs a Postgres the tests may create a database on
TEST_DATABASE_URL=postgresql://postgres@localhost:5432/postgres \
  python -m unittest discover -s backend/tests -p 'test_*.py'

# frontend
node --test frontend/tests/api-config.test.mjs
(cd frontend && CI=true yarn build)
```

The backend suite runs the real app against a real database, including a
check that the SQL analytics give the same answers as the original Python
implementation on awkward data.
