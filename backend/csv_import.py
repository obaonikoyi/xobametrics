import io
import csv as csvmod

# Canonical fields we ingest from any platform CSV export.
CANONICAL_FIELDS = ["date", "views", "plays", "likes", "comments", "shares", "followers"]

# Common header aliases across platform CSV exports (lowercased, stripped).
ALIASES = {
    "date": ["date", "day", "period", "timestamp", "time", "report date"],
    "views": ["views", "view", "video views", "impressions", "watch", "plays (video)"],
    "plays": ["plays", "play", "streams", "stream", "total plays", "listens", "spins"],
    "likes": ["likes", "like", "hearts", "favorites", "reactions", "thumbs up"],
    "comments": ["comments", "comment", "replies"],
    "shares": ["shares", "share", "reposts", "repost", "retweets"],
    "followers": ["followers", "follower", "subscribers", "subs", "fans", "new followers"],
}


def _clean(v):
    if v is None:
        return 0.0
    s = str(v).strip().replace(",", "").replace("$", "")
    if s == "" or s.lower() in ("na", "n/a", "null", "-"):
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def parse_csv(raw: bytes):
    """Parse raw csv bytes -> (headers, rows[list of dict], suggested_mapping)."""
    text = raw.decode("utf-8-sig", errors="replace")
    reader = csvmod.DictReader(io.StringIO(text))
    headers = reader.fieldnames or []
    rows = [dict(r) for r in reader]
    suggested = suggest_mapping(headers)
    return headers, rows[:500], suggested


def suggest_mapping(headers):
    """Map raw headers -> canonical field names using alias matching."""
    mapping = {}
    lowered = {h: (h or "").strip().lower() for h in headers}
    for canonical, aliases in ALIASES.items():
        for h, hl in lowered.items():
            if hl in aliases or any(a in hl for a in aliases):
                mapping[canonical] = h
                break
    return mapping


def normalize_rows(rows, mapping):
    """Apply mapping -> canonical rows with cumulative metric conversion.

    Detects whether the source is daily-incremental or already-cumulative and
    always returns cumulative snapshots (what the analytics layer expects).
    """
    date_col = mapping.get("date")
    metric_cols = {k: mapping[k] for k in CANONICAL_FIELDS if k != "date" and k in mapping}
    out = []
    for r in rows:
        d = str(r.get(date_col, "")).strip()[:10] if date_col else ""
        if not d:
            continue
        rec = {"date": d}
        for canonical, col in metric_cols.items():
            rec[canonical] = _clean(r.get(col))
        out.append(rec)
    out.sort(key=lambda x: x["date"])
    if not out:
        return out

    # Heuristic: if the running series never decreases for the primary metric it's cumulative,
    # otherwise treat as daily increments and accumulate.
    primary = "plays" if "plays" in metric_cols else ("views" if "views" in metric_cols else None)
    is_incremental = False
    if primary:
        seq = [row.get(primary, 0) for row in out]
        decreases = sum(1 for i in range(1, len(seq)) if seq[i] < seq[i - 1])
        is_incremental = decreases > len(seq) * 0.25

    if is_incremental:
        running = {k: 0.0 for k in metric_cols}
        for row in out:
            for k in metric_cols:
                running[k] += row.get(k, 0)
                row[k] = running[k]
    return out
