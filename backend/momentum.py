"""
Momentum: what is changing, not just what has accumulated.

Snapshots store running totals. Everything here works from the *gain* between
two consecutive observed days of the same content item, so a day an item was
not observed is left out rather than read as a drop, and a new item joining a
release is not read as a spike. Day 0 counts the release's first-day total as
its gain, since there is no earlier day for it to grow from.
"""
from datetime import date, timedelta
from statistics import median

from analytics import _DAILY_SNAPSHOTS, _metric, profile_overview, release_race
from database import db

MILESTONES = (1_000, 10_000, 100_000, 1_000_000, 10_000_000)
# A day counts as a spike when it gains at least this many times the usual
# day, and at least SPIKE_MIN_GAIN, so a quiet song going from 3 to 9 views is
# not "taking off".
SPIKE_RATIO = 2.0
SPIKE_MIN_GAIN = 25
BASELINE_DAYS = 14
MIN_BASELINE_POINTS = 5


async def _daily_gains(scope: str, arg, column: str) -> list[dict]:
    """
    (release_id, date, gained) for every release-day whose gain is complete:
    each item already being tracked that day has a reading for it and for the
    day before. A day any of them missed is left out rather than undercounted.
    """
    return await db.fetch(
        f"""
        WITH daily AS ({_DAILY_SNAPSHOTS.format(scope=scope)}),
        steps AS (
            SELECT d.content_item_id, d.item_release_id AS release_id, d.date, d.{column} AS value,
                   LAG(d.date) OVER w AS prev_date, LAG(d.{column}) OVER w AS prev_value,
                   r.release_date
            FROM daily d JOIN releases r ON r.id = d.item_release_id
            WINDOW w AS (PARTITION BY d.content_item_id ORDER BY d.date)
        ),
        spans AS (
            SELECT content_item_id, release_id, min(date) AS first_date, max(date) AS last_date
            FROM steps GROUP BY content_item_id, release_id
        ),
        gains AS (
            SELECT release_id, date,
                   sum(CASE WHEN prev_date = date - 1 THEN GREATEST(value - prev_value, 0)
                            ELSE value END)::bigint AS gained,
                   count(*) FILTER (WHERE prev_date = date - 1) AS steps
            FROM steps
            WHERE prev_date = date - 1 OR (prev_date IS NULL AND date = release_date)
            GROUP BY release_id, date
        )
        SELECT g.release_id, g.date, g.gained
        FROM gains g
        WHERE g.steps = (
            SELECT count(*) FROM spans s
            WHERE s.release_id = g.release_id AND s.first_date < g.date AND s.last_date >= g.date
        )
        ORDER BY g.release_id, g.date
        """,
        arg,
    )


def _with_average(points: list[dict]) -> list[dict]:
    """Add a trailing 7-day average, only where at least 4 of those days were observed."""
    by_day = {p["date"]: p["value"] for p in points}
    out = []
    for p in points:
        d = date.fromisoformat(p["date"])
        window = [by_day[k] for k in ((d - timedelta(days=i)).isoformat() for i in range(7)) if k in by_day]
        avg = round(sum(window) / len(window)) if len(window) >= 4 else None
        out.append({**p, "avg7": avg})
    return out


def _window_sum(by_day: dict, end: date, days: int) -> tuple[int, int]:
    """Sum and number of observed days in the `days` days ending at `end`."""
    values = [by_day[k] for k in ((end - timedelta(days=i)).isoformat() for i in range(days)) if k in by_day]
    return sum(values), len(values)


def _spike(series: list[dict]) -> dict | None:
    """The latest day's gain against the median of the days before it."""
    if len(series) < MIN_BASELINE_POINTS + 1:
        return None
    latest = series[-1]
    latest_day = date.fromisoformat(latest["date"])
    start = latest_day - timedelta(days=BASELINE_DAYS)
    baseline = [p["value"] for p in series[:-1] if date.fromisoformat(p["date"]) >= start]
    if len(baseline) < MIN_BASELINE_POINTS:
        return None
    usual = median(baseline)
    if latest["value"] < SPIKE_MIN_GAIN or latest["value"] < SPIKE_RATIO * max(usual, 1):
        return None
    return {"date": latest["date"], "gained": latest["value"], "usual": round(usual),
            "ratio": round(latest["value"] / max(usual, 1), 1)}


def _milestones(race_series: list[dict], release_date: str) -> list[dict]:
    """The first day each threshold was reached, from the Day-0-aligned totals."""
    out = []
    start = date.fromisoformat(release_date)
    for threshold in MILESTONES:
        hit = next((p for p in race_series if p["value"] >= threshold), None)
        if hit:
            out.append({"threshold": threshold, "day": hit["day"],
                        "date": (start + timedelta(days=hit["day"])).isoformat()})
    return out


def _benchmarks(race: dict, days=(7, 28)) -> dict:
    """
    Each release's total on Day N against the median of the releases that came
    out before it, compared only where both were actually observed on Day N.
    """
    releases = sorted(race["releases"], key=lambda r: r["release_date"])
    out = {}
    for i, r in enumerate(releases):
        by_day = {p["day"]: p["value"] for p in r["series"]}
        marks = {}
        for n in days:
            value = by_day.get(n)
            earlier = [
                v for v in (
                    {p["day"]: p["value"] for p in prev["series"]}.get(n) for prev in releases[:i]
                ) if v is not None
            ]
            usual = median(earlier) if len(earlier) >= 2 else None
            marks[f"day{n}"] = {
                "value": value,
                "usual": round(usual) if usual is not None else None,
                "compared_with": len(earlier),
                "index": round(value / usual, 2) if value is not None and usual else None,
            }
        out[r["release_id"]] = marks
    return out


async def profile_momentum(profile_id: str, metric: str = "reach", days: int = 90) -> dict:
    column = _metric(metric)
    rows = await _daily_gains("c.profile_id = $1", profile_id, column)
    overview = await profile_overview(profile_id)
    titles = {r["id"]: r for r in overview["releases"]}

    per_release: dict[str, list[dict]] = {}
    total: dict[str, int] = {}
    for r in rows:
        per_release.setdefault(r["release_id"], []).append({"date": r["date"], "value": r["gained"]})
        total[r["date"]] = total.get(r["date"], 0) + r["gained"]

    latest = max(total) if total else None
    daily = []
    week = None
    if latest:
        end = date.fromisoformat(latest)
        first = (end - timedelta(days=days - 1)).isoformat()
        daily = _with_average([{"date": d, "value": v} for d, v in sorted(total.items()) if d >= first])
        this_week, this_days = _window_sum(total, end, 7)
        last_week, last_days = _window_sum(total, end - timedelta(days=7), 7)
        week = {
            "through": latest,
            "this_week": this_week, "this_week_days": this_days,
            "last_week": last_week, "last_week_days": last_days,
            # Only compared when both weeks were fully observed.
            "change": round((this_week - last_week) / last_week, 3)
            if this_days == 7 and last_days == 7 and last_week > 0 else None,
        }

    alerts = []
    for release_id, series in per_release.items():
        # Only releases observed within the last three days can be taking off now.
        if not latest or (date.fromisoformat(latest) - date.fromisoformat(series[-1]["date"])).days > 3:
            continue
        spike = _spike(series)
        if spike and release_id in titles:
            alerts.append({"release_id": release_id, "title": titles[release_id]["title"], **spike})
    alerts.sort(key=lambda a: a["ratio"], reverse=True)

    release_ids = list(titles)
    race = await release_race(profile_id, release_ids, metric=column, max_day=3650) if release_ids else {"releases": []}
    benchmarks = _benchmarks(race)
    milestones = []
    recent = (date.fromisoformat(latest) - timedelta(days=60)).isoformat() if latest else None
    for r in race["releases"]:
        for m in _milestones(r["series"], r["release_date"]):
            if recent and m["date"] >= recent:
                milestones.append({"release_id": r["release_id"], "title": r["title"], **m})
    # Several thresholds passed on one day read as one milestone: the biggest.
    biggest = {}
    for m in milestones:
        key = (m["release_id"], m["date"])
        if key not in biggest or m["threshold"] > biggest[key]["threshold"]:
            biggest[key] = m
    milestones = sorted(biggest.values(), key=lambda m: (m["date"], m["threshold"]), reverse=True)

    quality = []
    for r in overview["releases"]:
        reach = r["reach"]
        if reach < 100:
            continue
        quality.append({
            "release_id": r["id"], "title": r["title"], "reach": reach,
            "engagement_rate": round(r["engagement"] / reach, 4),
            "followers_per_1k": round(r["followers"] * 1000 / reach, 2),
        })

    return {
        "metric": metric,
        "daily": daily,
        "week": week,
        "alerts": alerts,
        "milestones": milestones[:12],
        "benchmarks": benchmarks,
        "quality": quality,
    }


async def release_momentum(profile_id: str, release_id: str, metric: str = "reach") -> dict:
    column = _metric(metric)
    rows = await _daily_gains("c.release_id = $1", release_id, column)
    daily = _with_average([{"date": r["date"], "value": r["gained"]} for r in rows])
    everything = await profile_momentum(profile_id, metric)
    race = await release_race(profile_id, [release_id], metric=column, max_day=3650)
    return {
        "metric": metric,
        "daily": daily,
        "spike": _spike(daily),
        "benchmark": everything["benchmarks"].get(release_id),
        "quality": next((q for q in everything["quality"] if q["release_id"] == release_id), None),
        "milestones": _milestones(race["releases"][0]["series"], race["releases"][0]["release_date"])
        if race["releases"] else [],
    }
