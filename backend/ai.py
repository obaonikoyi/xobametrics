import json
from fastapi import HTTPException

import analytics
from ai_provider import build_provider
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


async def _ask(prompt: str) -> str:
    """
    Send one grounded prompt and return the text.

    Built per call rather than held, so a key or model configured after
    start-up takes effect without a restart -- and so a deployment with no
    model configured still starts and still serves its analytics.
    """
    provider = build_provider()
    if not getattr(provider, "configured", False):
        raise HTTPException(
            status_code=503,
            detail="AI insights are not configured yet. Your stored analytics are still available.",
        )
    return await provider.complete(SYSTEM_PROMPT, prompt)


def _fmt(n):
    try:
        return f"{int(round(n)):,}"
    except Exception:
        return str(n)


async def _build_facts(profile_id: str, release_id=None) -> dict:
    rel = None
    if release_id:
        rel = await db.releases.find_one({"id": release_id, "profile_id": profile_id}, {"_id": 0})
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


async def generate_insight(profile_id: str, release_id=None) -> dict:
    facts = await _build_facts(profile_id, release_id)
    if facts["release_count"] == 0:
        return {
            "summary": "There is no data yet for this profile. Upload a CSV to start tracking releases.",
            "recommendations": [],
            "grounded": False,
        }
    prompt = (
        "Here are the FACTS computed by the backend:\n"
        + json.dumps(facts, indent=2)
        + "\n\nWrite a tight performance summary (3-5 sentences) referencing the real figures, "
        "then 3 concrete recommendations. Respond as JSON with keys 'summary' (string) and "
        "'recommendations' (array of short strings). Only use the numbers above."
    )
    resp = await _ask(prompt)
    return _parse_json_response(resp, facts)


async def answer_question(profile_id: str, question: str) -> dict:
    facts = await _build_facts(profile_id)
    prompt = (
        "FACTS (backend-computed, the only numbers you may use):\n"
        + json.dumps(facts, indent=2)
        + f"\n\nUser question: {question}\n\n"
        "Answer using ONLY the facts above. If the facts are insufficient, say so plainly. "
        "Reference specific figures. Keep it to a few sentences."
    )
    resp = await _ask(prompt)
    return {"answer": resp.strip(), "grounded": facts["release_count"] > 0, "facts_used": facts}


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
