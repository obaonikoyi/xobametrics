import os
import json
from emergentintegrations.llm.chat import LlmChat, UserMessage

import analytics
from database import db

MODEL_PROVIDER = "openai"
MODEL_NAME = "gpt-5.6-luna"

SYSTEM_PROMPT = (
    "You are Xoba AI, the analyst for XobaMetrics, a creator analytics platform.\n"
    "STRICT GROUNDING RULES:\n"
    "1. You are ONLY an explainer. All numbers are computed by the backend and given to you as FACTS (JSON).\n"
    "2. NEVER invent, estimate, or guess any metric. Use ONLY numbers present in the FACTS.\n"
    "3. If the FACTS do not contain enough data to answer, clearly say the data is insufficient and suggest connecting a platform or uploading a CSV. Do NOT fabricate.\n"
    "4. Be concise, specific and reference the actual figures. Format numbers with commas.\n"
    "5. Talk like a sharp music-industry data analyst. No fluff.\n"
)


def _chat(session_id: str) -> LlmChat:
    return LlmChat(
        api_key=os.environ["EMERGENT_LLM_KEY"],
        session_id=session_id,
        system_message=SYSTEM_PROMPT,
    ).with_model(MODEL_PROVIDER, MODEL_NAME)


def _fmt(n):
    try:
        return f"{int(round(n)):,}"
    except Exception:
        return str(n)


async def _build_facts(profile_id: str, release_id=None) -> dict:
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
        rel = await db.releases.find_one({"id": release_id}, {"_id": 0})
        facts["focus_release"] = {
            "title": rel["title"] if rel else None,
            "release_date": rel["release_date"] if rel else None,
            "totals": rt["totals"],
            "per_platform": rt["per_platform"],
            "content_count": rt["content_count"],
        }
    # first-week (Day 0-7) reach per release for fair comparison via race data
    rids = [r["id"] for r in overview["releases"]]
    if rids:
        race = await analytics.release_race(profile_id, rids, metric="reach", max_day=7)
        first_week = []
        for r in race["releases"]:
            val = r["series"][-1]["value"] if r["series"] else 0
            first_week.append({"title": r["title"], "first_7_days_reach": val})
        facts["first_week_reach"] = first_week
    return facts


async def generate_insight(profile_id: str, release_id=None) -> dict:
    facts = await _build_facts(profile_id, release_id)
    if facts["release_count"] == 0:
        return {
            "summary": "There is no data yet for this profile. Connect a platform or upload a CSV to start tracking releases.",
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
    chat = _chat(f"insight_{profile_id}")
    resp = await chat.send_message(UserMessage(text=prompt))
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
    chat = _chat(f"ask_{profile_id}")
    resp = await chat.send_message(UserMessage(text=prompt))
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
