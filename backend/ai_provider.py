"""
The model call, behind an interface.

XobaPulse's architecture rule 3 -- AI providers sit behind interfaces so they
can be changed -- applies here too, and this file is what brings XobaMetrics in
line with it. Before this, `ai.py` imported a vendor's chat wrapper directly, so
changing model provider meant rewriting the module and the backend could not
install at all without a wheel served from that vendor's CDN.

A provider takes a system prompt and a user message and returns text. That is
the entire surface the analyst layer needs, so it is the entire interface.
"""
import os
from typing import Protocol


class AiProvider(Protocol):
    """Anything that can answer a prompt with text."""

    async def complete(self, system_prompt: str, user_message: str, schema: dict | None = None) -> str: ...


class NotConfiguredProvider:
    """
    Stands in when no API key is set.

    The analytics in this product are computed by the backend and do not need a
    model; only the explanations do. So a missing key degrades the AI panel
    rather than the application, and says so in words a user can act on.
    """

    configured = False

    async def complete(self, system_prompt: str, user_message: str, schema: dict | None = None) -> str:
        raise RuntimeError(
            "AI insights are not configured yet. Your stored analytics are still available."
        )


class AiRefused(Exception):
    """The model declined the request, even after its fallback."""


class ClaudeProvider:
    """
    Claude, through the Anthropic API.

    Stateless on purpose: every request carries the full backend-computed facts
    and the grounding rules, so an answer is reproducible from the request
    alone. `schema`, when given, makes the reply JSON matching it.
    """

    configured = True

    def __init__(self, api_key: str, model: str):
        # Imported here so the module loads for callers that never use it --
        # a missing optional dependency should not break application start-up.
        from anthropic import AsyncAnthropic

        self._client = AsyncAnthropic(api_key=api_key)
        self._model = model

    async def complete(self, system_prompt: str, user_message: str, schema: dict | None = None) -> str:
        extra = {"output_config": {"format": {"type": "json_schema", "schema": schema}}} if schema else {}
        response = await self._client.beta.messages.create(
            model=self._model,
            max_tokens=16000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
            thinking={"type": "adaptive"},
            # A request the model's safety checks decline is re-run on the
            # model Anthropic recommends for that case instead of failing.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            **extra,
        )
        if response.stop_reason == "refusal":
            raise AiRefused()
        return "".join(block.text for block in response.content if block.type == "text")


DEFAULT_MODEL = "claude-opus-5"


def build_provider() -> AiProvider:
    """
    The provider this deployment is configured for: Claude when
    ANTHROPIC_API_KEY is set. AI_MODEL overrides the model.
    """
    api_key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    if not api_key:
        return NotConfiguredProvider()
    return ClaudeProvider(api_key, (os.environ.get("AI_MODEL") or "").strip() or DEFAULT_MODEL)
