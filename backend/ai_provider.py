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

    async def complete(self, system_prompt: str, user_message: str) -> str: ...


class NotConfiguredProvider:
    """
    Stands in when no API key is set.

    The analytics in this product are computed by the backend and do not need a
    model; only the explanations do. So a missing key degrades the AI panel
    rather than the application, and says so in words a user can act on.
    """

    configured = False

    async def complete(self, system_prompt: str, user_message: str) -> str:
        raise RuntimeError(
            "AI insights are not configured yet. Your stored analytics are still available."
        )


class OpenAiProvider:
    """
    The OpenAI chat completions API, called directly.

    Stateless on purpose. The previous wrapper kept a server-side session per
    conversation; nothing here needs it, because every request already carries
    the full backend-computed facts and the grounding rules. Sending the whole
    context each time is what makes the answer reproducible from the request
    alone.
    """

    configured = True

    def __init__(self, api_key: str, model: str):
        # Imported here so the module loads for callers that never use it --
        # a missing optional dependency should not break application start-up.
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model

    async def complete(self, system_prompt: str, user_message: str) -> str:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        )
        return response.choices[0].message.content or ""


def build_provider() -> AiProvider:
    """
    The provider this deployment is configured for.

    AI_MODEL has no default. A model identifier in source is not evidence that
    the provider serves it, and a wrong default fails at request time with a
    message about the model rather than about the configuration -- so the
    absence of a model is treated the same as the absence of a key.
    """
    api_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    model = (os.environ.get("AI_MODEL") or "").strip()
    if not api_key or not model:
        return NotConfiguredProvider()
    return OpenAiProvider(api_key, model)
