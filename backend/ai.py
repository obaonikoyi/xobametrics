import asyncio
import json
from fastapi import HTTPException

import analytics
from ai_provider import AiRefused, build_provider
from database import db

SYSTEM_PROMPT = (
    "You are Xoba AI, the analyst for XobaMetrics, a creator analytics platform.\n"
    "STRICT GROUNDING RULES:\n"
    "1. You are ONLY an explainer. All numbers are computed by the backend and given to you as FACTS (JSON).\n"
    "2. NEVER invent, estimate, or guess any metric. Use ONLY numbers present in the FACTS.\n"
    "3. If the FACTS do not contain enough data to answer, clearly say the data is insufficient and suggest connecting a platform or uploading a CSV. Do NOT fabricate.\n"
    "4. Be concise, specific and reference the actual figures. Format numbers with commas.\n"
    "5. Talk like a sharp music-industry data analyst. No fluff.\n"
    "6. Null means unavailable, not zero. A latest observed point is not a complete first-week total.\n"
)


async def _ask(prompt: str, schema: dict | None = None) -> str:
    """
    Send one grounded prompt and return the text.

    Built per call rather than held, so a key or model configured after
    start-up takes effect without a restart -- and so a deployment with no
    model configured still starts and still serves its analytics.
    """
    import anthropic

    provider = build_provider()
    if not getattr(provider, "configured", False):
        raise HTTPException(
            status_code=503,
            detail="AI insights are not configured yet. Your stored analytics are still available.",
        )
    try:
        return await provider.complete(SYSTEM_PROMPT, prompt, schema)
    except AiRefused:
        raise HTTPException(status_code=422, detail="The AI declined this question. Try asking it another way.")
    except anthropic.AuthenticationError:
        raise HTTPException(status_code=503, detail="The AI key was rejected. Check ANTHROPIC_API_KEY.")
    except anthropic.PermissionDeniedError:
        raise HTTPException(status_code=503, detail="The AI account cannot use this model. Check its credit and access.")
    except anthropic.RateLimitError:
        raise HTTPException(status_code=503, detail="The AI is busy right now. Please try again in a minute.")
    except (anthropic.APIStatusError, anthropic.APIConnectionError):
        raise HTTPException(status_code=502, detail="The AI could not be reached. Please try again.")


def _fmt(n):
    try:
        return f"{int(round(n)):,}"
    except Exception:
        return str(n)


async def _build_facts(profile_id: str, release_id=None) -> dict:
    rel = None
    if release_id:
        rel = await db.find_one("releases", {"id": release_id, "profile_id": profile_id})
        if not rel:
            raise HTTPException(status_code=404, detail="Release not found")
    overview = await analytics.profile_overview(profile_id)
    facts = {
        "profile_totals": overview["totals"],
        "release_count": overview["release_count"],
        "platform_breakdown": overview["platform_breakdown"],
        "releases": overview["releases"],
        "top_release": overview["top_release"],
        "last_synced": overview["last_synced"],
    }
    if release_id:
        rt = await analytics.release_totals(release_id)
        facts["focus_release"] = {
            "title": rel["title"],
            "release_date": rel["release_date"],
            "totals": rt["totals"],
            "per_platform": rt["per_platform"],
            "content_count": rt["content_count"],
        }
    rids = [r["id"] for r in overview["releases"]]
    if rids:
        race = await analytics.release_race(profile_id, rids, metric="reach", max_day=7)
        first_week = []
        for r in race["releases"]:
            points = sorted(r["series"], key=lambda p: p["day"])
            latest = points[-1] if points else None
            day_seven = next((p for p in points if p["day"] == 7), None)
            first_week.append({
                "title": r["title"],
                "observed_day_7_reach": day_seven["value"] if day_seven else None,
                "latest_observed_reach": latest["value"] if latest else None,
                "observed_through_day": latest["day"] if latest else None,
                "coverage": "day_7_observed" if day_seven else "incomplete",
            })
        facts["first_week_reach"] = first_week
        facts["first_week_note"] = (
            "Day 0 is the original release date. Missing observations are unknown, not zero. "
            "Points sum only content observed on that day; campaign completeness has not been verified. "
            "Do not describe partial observations as complete first-week performance."
        )
    return facts


AUDIENCE_TIMEOUT_SECONDS = 10


def _momentum_facts(m: dict, titles: dict) -> dict:
    """The parts of the momentum analytics an artist asks about, keyed by title."""
    benchmarks = []
    for release_id, marks in m["benchmarks"].items():
        compared = {day: mark for day, mark in marks.items() if mark["index"] is not None}
        if compared and release_id in titles:
            benchmarks.append({"title": titles[release_id], **{
                day: {"value": mark["value"], "usual_for_earlier_releases": mark["usual"],
                      "times_usual": mark["index"], "earlier_releases_compared": mark["compared_with"]}
                for day, mark in compared.items()
            }})
    return {
        "metric": m["metric"],
        "week": m["week"],
        "taking_off": [
            {"title": a["title"], "date": a["date"], "gained": a["gained"],
             "usual_daily_gain": a["usual"], "times_usual": a["ratio"]}
            for a in m["alerts"]
        ],
        "recent_milestones": [
            {"title": x["title"], "reached": x["threshold"], "days_after_release": x["day"], "date": x["date"]}
            for x in m["milestones"][:8]
        ],
        "vs_earlier_releases": benchmarks,
        "fan_quality": m["quality"],
    }


def _ranked(rows: list[dict], key: str, value: str, limit: int) -> list[dict]:
    return [{key: r[key], value: r[value], "share": r["share"]} for r in rows[:limit]]


async def _trend_facts(profile_id: str, release_id: str | None = None) -> dict:
    """
    Momentum, YouTube audience and distributor-report facts. Each part is
    optional: one that fails or has no data is described, not dropped silently,
    so the model can say what is missing instead of guessing.
    """
    import imports
    import momentum
    import youtube_audience

    facts = {}
    profile = await db.find_one("creator_profiles", {"id": profile_id})
    titles = {r["id"]: r["title"] for r in await db.find("releases", {"profile_id": profile_id})}

    try:
        facts["momentum"] = _momentum_facts(await momentum.profile_momentum(profile_id), titles)
    except Exception:
        facts["momentum"] = {"status": "unavailable"}

    try:
        audience = await asyncio.wait_for(
            youtube_audience.audience_report(profile_id, profile["owner_id"], release_id, 365 if release_id else 28),
            AUDIENCE_TIMEOUT_SECONDS,
        )
        if audience["status"] == "ok":
            audience = {
                "status": "ok", "period": f"{audience['start']} to {audience['end']}",
                "total_views": audience["total_views"],
                "where_views_come_from": _ranked(audience["traffic"], "source", "views", 8),
                "top_countries": _ranked(audience["countries"], "country", "views", 10),
            }
        else:
            audience = {"status": audience["status"]}
    except Exception:
        audience = {"status": "unavailable"}
    facts["youtube_audience"] = {"scope": titles.get(release_id, "whole channel"), **audience}

    try:
        sales = await imports.distributor_breakdown(profile_id, release_id)
        if sales["status"] == "ok":
            sales = {
                "status": "ok", "months": f"{sales['first_month'][:7]} to {sales['last_month'][:7]}",
                "total_streams": sales["total_units"],
                "top_countries": _ranked(sales["countries"], "country", "units", 10),
                "by_store": _ranked(sales["stores"], "platform", "units", 10),
            }
    except Exception:
        sales = {"status": "unavailable"}
    facts["distributor_reports"] = sales

    facts["trend_notes"] = (
        "momentum.week compares the gain over the last 7 observed days with the 7 before; change is null "
        "unless both weeks were fully observed. taking_off lists songs whose latest daily gain is well above "
        "their usual day. vs_earlier_releases compares a song's Day 7 / Day 28 total with the median of the "
        "artist's earlier releases (times_usual 1.5 = 50% better). fan_quality: engagement_rate is "
        "interactions (likes, comments and shares where the platform reports them) per reach; followers_per_1k is new followers per 1,000 reach. "
        "youtube_audience covers YouTube only. distributor_reports cover every store from uploaded "
        "monthly reports, which usually run 2-3 months behind. Country codes are ISO 3166 two-letter codes: "
        "write the country's name. A status other than ok means that data is not available: say so and "
        "say how to get it (connect YouTube with Analytics permission, or upload a distributor report)."
    )
    return facts


INSIGHT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "recommendations": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "recommendations"],
    "additionalProperties": False,
}


async def generate_insight(profile_id: str, release_id=None) -> dict:
    facts = await _build_facts(profile_id, release_id)
    if facts["release_count"] == 0:
        return {
            "summary": "There is no data yet for this profile. Upload a CSV to start tracking releases.",
            "recommendations": [],
            "grounded": False,
        }
    facts.update(await _trend_facts(profile_id, release_id))
    prompt = (
        "Here are the FACTS computed by the backend:\n"
        + json.dumps(facts, indent=2)
        + "\n\nWrite a tight performance summary (3-5 sentences) referencing the real figures, "
        "then 3 concrete recommendations. Respond as JSON with keys 'summary' (string) and "
        "'recommendations' (array of short strings). Only use the numbers above."
    )
    resp = await _ask(prompt, INSIGHT_SCHEMA)
    return _parse_json_response(resp, facts)


ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "follow_ups": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["answer", "follow_ups"],
    "additionalProperties": False,
}


async def answer_question(profile_id: str, question: str) -> dict:
    facts = await _build_facts(profile_id)
    if facts["release_count"] > 0:
        facts.update(await _trend_facts(profile_id))
    prompt = (
        "FACTS (backend-computed, the only numbers you may use):\n"
        + json.dumps(facts, indent=2)
        + f"\n\nUser question: {question}\n\n"
        "Answer using ONLY the facts above. If the facts are insufficient, say so plainly. "
        "Reference specific figures. Keep it to a few sentences. "
        "Then suggest 2-3 short follow-up questions (under 12 words each) the artist might ask next, "
        "that the facts above can answer."
    )
    resp = await _ask(prompt, ANSWER_SCHEMA)
    try:
        data = json.loads(resp)
        answer = str(data.get("answer", "")).strip()
        follow_ups = [str(q).strip() for q in data.get("follow_ups", []) if str(q).strip()][:3]
    except Exception:
        answer, follow_ups = resp.strip(), []
    return {
        "answer": answer,
        "follow_ups": follow_ups,
        "grounded": facts["release_count"] > 0,
        "facts_used": facts,
    }


def _parse_json_response(resp: str, facts: dict) -> dict:
    text = resp.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    try:
        data = json.loads(text)
        return {
            "summary": data.get("summary", ""),
            "recommendations": data.get("recommendations", []),
            "grounded": True,
        }
    except Exception:
        return {"summary": resp.strip(), "recommendations": [], "grounded": True}
