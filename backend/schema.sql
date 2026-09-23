-- XobaMetrics schema. Applied at startup; every statement is idempotent.
--
-- Rows keep the ids the application has always used (user_…, rel_…, snap_…)
-- so links, share URLs and anything copied from the old database stay valid.
-- Ownership columns (owner_id, profile_id, workspace_id) are repeated on child
-- rows because every query is scoped by them; foreign keys keep them honest.

CREATE TABLE IF NOT EXISTS users (
    user_id        TEXT PRIMARY KEY,
    email          TEXT NOT NULL UNIQUE,
    name           TEXT,
    picture        TEXT,
    password_hash  TEXT,
    role           TEXT NOT NULL DEFAULT 'user',
    auth_provider  TEXT NOT NULL DEFAULT 'password',
    google_sub     TEXT UNIQUE,
    beta_approved  BOOLEAN NOT NULL DEFAULT TRUE,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One row per signed-in browser. Access tokens name their session, so signing
-- out (or an administrator) can end a token before it expires.
CREATE TABLE IF NOT EXISTS user_sessions (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ NOT NULL,
    revoked_at  TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS user_sessions_user_idx ON user_sessions (user_id);

CREATE TABLE IF NOT EXISTS login_attempts (
    identifier    TEXT PRIMARY KEY,
    count         INTEGER NOT NULL DEFAULT 0,
    locked_until  TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS workspaces (
    id          TEXT PRIMARY KEY,
    owner_id    TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    type        TEXT NOT NULL DEFAULT 'solo',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS workspaces_owner_idx ON workspaces (owner_id);

CREATE TABLE IF NOT EXISTS creator_profiles (
    id            TEXT PRIMARY KEY,
    workspace_id  TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    owner_id      TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    name          TEXT NOT NULL,
    genre         TEXT,
    avatar        TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS creator_profiles_owner_idx ON creator_profiles (owner_id);
CREATE INDEX IF NOT EXISTS creator_profiles_workspace_idx ON creator_profiles (workspace_id);

CREATE TABLE IF NOT EXISTS platform_connections (
    id                       TEXT PRIMARY KEY,
    profile_id               TEXT NOT NULL REFERENCES creator_profiles(id) ON DELETE CASCADE,
    workspace_id             TEXT REFERENCES workspaces(id) ON DELETE CASCADE,
    owner_id                 TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    platform                 TEXT NOT NULL,
    source                   TEXT,
    status                   TEXT NOT NULL DEFAULT 'needs_auth',
    account_name             TEXT,
    external_account_id      TEXT,
    access_token_enc         TEXT,
    refresh_token_enc        TEXT,
    access_token_expires_at  TIMESTAMPTZ,
    scopes                   TEXT[],
    connected_at             TIMESTAMPTZ,
    last_synced_at           TIMESTAMPTZ,
    last_error               TEXT,
    channel_statistics       JSONB,
    account_statistics       JSONB,
    history_backfill_status  TEXT,
    history_backfilled_at    TIMESTAMPTZ,
    history_start_date       DATE,
    history_end_date         DATE,
    history_rows_received    INTEGER,
    history_points_written   INTEGER,
    history_last_error       TEXT,
    -- A profile has at most one connection per platform.
    UNIQUE (profile_id, platform)
);
CREATE INDEX IF NOT EXISTS platform_connections_status_idx ON platform_connections (status, platform);

CREATE TABLE IF NOT EXISTS releases (
    id                  TEXT PRIMARY KEY,
    profile_id          TEXT NOT NULL REFERENCES creator_profiles(id) ON DELETE CASCADE,
    workspace_id        TEXT REFERENCES workspaces(id) ON DELETE CASCADE,
    owner_id            TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    title               TEXT NOT NULL,
    release_date        DATE NOT NULL,
    cover               TEXT,
    description         TEXT,
    source              TEXT,
    source_external_id  TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS releases_profile_idx ON releases (profile_id);

CREATE TABLE IF NOT EXISTS content_items (
    id              TEXT PRIMARY KEY,
    release_id      TEXT NOT NULL REFERENCES releases(id) ON DELETE CASCADE,
    profile_id      TEXT NOT NULL REFERENCES creator_profiles(id) ON DELETE CASCADE,
    workspace_id    TEXT REFERENCES workspaces(id) ON DELETE CASCADE,
    owner_id        TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    title           TEXT NOT NULL,
    platform        TEXT NOT NULL,
    content_type    TEXT,
    url             TEXT,
    -- Kept as the platform sent it: a full timestamp from YouTube, a date from CSV.
    published_at    TEXT,
    thumbnail       TEXT,
    external_id     TEXT,
    channel_id      TEXT,
    soundcloud_urn  TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- The same platform video or track is imported once per profile.
    UNIQUE (profile_id, platform, external_id)
);
CREATE INDEX IF NOT EXISTS content_items_release_idx ON content_items (release_id);

CREATE TABLE IF NOT EXISTS metric_snapshots (
    id                           TEXT PRIMARY KEY,
    content_item_id              TEXT NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
    release_id                   TEXT NOT NULL REFERENCES releases(id) ON DELETE CASCADE,
    profile_id                   TEXT NOT NULL REFERENCES creator_profiles(id) ON DELETE CASCADE,
    date                         DATE NOT NULL,
    day_offset                   INTEGER,
    views                        BIGINT NOT NULL DEFAULT 0,
    plays                        BIGINT NOT NULL DEFAULT 0,
    likes                        BIGINT NOT NULL DEFAULT 0,
    comments                     BIGINT NOT NULL DEFAULT 0,
    shares                       BIGINT NOT NULL DEFAULT 0,
    reach                        BIGINT NOT NULL DEFAULT 0,
    engagement                   BIGINT NOT NULL DEFAULT 0,
    followers                    BIGINT NOT NULL DEFAULT 0,
    -- Where the numbers came from. Manual rows (CSV, demo) share one source.
    source                       TEXT NOT NULL DEFAULT 'manual',
    metric_semantics             TEXT,
    history_first_observed_date  DATE,
    unavailable_metrics          TEXT[],
    observed_at                  TIMESTAMPTZ,
    -- One observation per item, per day, per source: re-running a sync or an
    -- import updates the day instead of adding a duplicate.
    UNIQUE (content_item_id, date, source)
);
CREATE INDEX IF NOT EXISTS metric_snapshots_release_idx ON metric_snapshots (release_id);

CREATE TABLE IF NOT EXISTS release_match_dismissals (
    profile_id    TEXT NOT NULL REFERENCES creator_profiles(id) ON DELETE CASCADE,
    owner_id      TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    match_key     TEXT NOT NULL,
    release_ids   TEXT[] NOT NULL,
    dismissed_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (profile_id, match_key)
);

CREATE TABLE IF NOT EXISTS reports (
    id                  TEXT PRIMARY KEY,
    profile_id          TEXT NOT NULL REFERENCES creator_profiles(id) ON DELETE CASCADE,
    owner_id            TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    title               TEXT NOT NULL,
    share_id            TEXT NOT NULL UNIQUE,
    totals              JSONB,
    platform_breakdown  JSONB,
    releases            JSONB,
    summary             TEXT,
    recommendations     JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS reports_profile_idx ON reports (profile_id);

CREATE TABLE IF NOT EXISTS files (
    id                 TEXT PRIMARY KEY,
    owner_id           TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    profile_id         TEXT REFERENCES creator_profiles(id) ON DELETE CASCADE,
    storage_path       TEXT,
    original_filename  TEXT,
    content_type       TEXT,
    is_deleted         BOOLEAN NOT NULL DEFAULT FALSE,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Short-lived OAuth and sign-in state. Each flow uses the columns it needs;
-- expired rows are removed by a periodic cleanup.
CREATE TABLE IF NOT EXISTS oauth_states (
    nonce              TEXT PRIMARY KEY,
    type               TEXT NOT NULL,
    owner_id           TEXT,
    profile_id         TEXT,
    user_id            TEXT,
    mode               TEXT,
    browser_key_hash   TEXT,
    oidc_nonce         TEXT,
    code_verifier      TEXT,
    pkce_verifier_enc  TEXT,
    invite_ok          BOOLEAN,
    expires_at         TIMESTAMPTZ NOT NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS oauth_states_expires_idx ON oauth_states (expires_at);
