# XobaMetrics — PRD

> **Stale in places — kept as the record of the original intent, September 2026.**
>
> Two lines below no longer describe the code and were the source of an
> incorrect claim in the README:
>
> - *"YouTube/SoundCloud OAuth is UI-stubbed for now"* — both are now real
>   OAuth implementations. See `backend/youtube.py` and `backend/soundcloud.py`.
> - *"Object Storage: Emergent object storage for CSV uploads"* — uploads now
>   go to a directory this deployment controls, via `UPLOAD_ARCHIVE_DIR`.
>
> The AI provider is also no longer the vendor's universal key; it is an
> interface in `backend/ai_provider.py`. The "Emergent-managed Google login"
> below has been removed: sign-in is email and password until a real Google
> OAuth sign-in flow is built. Read the code before trusting a line
> here.

## Original Problem Statement
AI-assisted creator analytics platform that starts with your own music/content data. Imports metrics (CSV + platform OAuth), snapshots them over time, auto-charts performance, compares releases fairly on a Day-0 timeline ("Release Race"), and answers plain-English questions grounded ONLY in backend-computed numbers (AI never touches the DB directly and never invents figures).

## User Choices
- AI: GPT 5.6 (openai `gpt-5.6-luna`) via Emergent Universal Key.
- Auth: BOTH email/password JWT AND Emergent-managed Google login.
- Theme: light + dark toggle (default dark). Brand: blue (cobalt).
- Scope: real OAuth credentials to be provided later → YouTube/SoundCloud OAuth is UI-stubbed for now; CSV is fully real.

## Architecture
- Frontend: React (JS/JSX) + Tailwind + shadcn/ui + Recharts + framer-motion. Contexts: Auth, Theme, Workspace, Ai.
- Backend: FastAPI, modular: database.py, models.py, auth.py, storage.py, csv_import.py, analytics.py (source-of-truth calculator), ai.py (grounded explainer), seed.py, routes.py, server.py.
- DB: MongoDB, relational model as referenced collections with UUID string ids (`_id` always stripped). Collections: users, user_sessions, workspaces, creator_profiles, platform_connections, releases, content_items, metric_snapshots, reports, files, login_attempts.
- Object Storage: Emergent object storage for CSV uploads.

## Data Model
User → Workspace → Creator Profile → Platform Connection → Release → Content Item → Metric Snapshot; plus Report. A Release groups many Content Items across platforms → campaign rollups + per-item detail. Day 0 = release_date; snapshots carry `day_offset` for fair Day-0 comparison.

## AI (hallucination-resistant)
Backend computes FACTS from analytics; the model receives only those numbers and narrates. `/ai/insights` (summary + recommendations) and `/ai/ask` (Q&A). Refuses to invent when data is insufficient.

## Implemented (2026-06-13) — MVP complete, 19/19 backend tests pass, frontend verified in-browser
- Auth: register/login (JWT) + Emergent Google login + /me + logout; brute-force lockout; data isolation by owner_id.
- Workspaces/profiles auto-created on signup; manager-ready profile switcher.
- Dashboard: KPI cards, grounded AI Performance Summary, reach-by-platform chart, top releases, guided empty state with demo-seed.
- Releases: list, create, detail with rollup + trajectory chart (metric selector) + content table with platform badges.
- Release Race (signature): Day-0 aligned multi-release chart, metric + day-range (7/14/30/90/All) controls.
- AI Q&A drawer: grounded answers + suggestion chips.
- Connections: platform cards with connected / needs_reconnect / needs_auth / syncing states; connect/reconnect/refresh; CSV.
- CSV import: upload → auto column mapping + preview → commit creates release + snapshots (real).
- Reports: generate (AI summary + recs + totals) + public share link (/share/:shareId).
- Theme toggle (persisted), responsive layout, data-testids throughout.

## Backlog / Remaining
- P0: Real YouTube Data API OAuth + `videos.batchGetStats`; scheduled sync worker (background snapshots).
- P1: SoundCloud OAuth 2.1 + PKCE; PDF/PNG report export (currently link-share + on-screen); CSV file re-parse from stored object on commit (currently commits from previewed rows).
- P2: Instagram/TikTok (app review), LinkedIn (Phase D); manager billing/paid tiers; token-expiry auto-detection from real APIs.

## Test Credentials
admin@xobametrics.com / XobaAdmin2026! (pre-seeded demo workspace "Luna Eclipse", 3 releases). See test_credentials.md.
