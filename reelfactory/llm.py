"""Thin structured-output wrapper around the Claude API."""

from __future__ import annotations

from typing import Protocol, TypeVar

import anthropic
from pydantic import BaseModel

from .prompts import SYSTEM

T = TypeVar("T", bound=BaseModel)


class GenerationError(RuntimeError):
    pass


class LLM(Protocol):
    async def generate(self, schema: type[T], prompt: str, *, effort: str | None = None) -> T: ...


class ClaudeLLM:
    """Streams one structured-output request per call and returns the parsed model.

    - Adaptive thinking is always on for Claude Opus 5.5; `effort` is the depth control.
    - `fallbacks: "default"` re-runs a request server-side on Anthropic's recommended model if
      a safety classifier declines it (crime/conspiracy niches can trip false positives).
    - Streaming avoids HTTP timeouts on long outputs (100 ideas, full visual plans).
    """

    def __init__(
        self,
        model: str = "claude-opus-5-5",
        effort: str = "high",
        client: anthropic.AsyncAnthropic | None = None,
        max_tokens: int = 64000,
        use_fallbacks: bool = True,
    ) -> None:
        self.model = model
        self.effort = effort
        self.client = client or anthropic.AsyncAnthropic()
        self.max_tokens = max_tokens
        self.use_fallbacks = use_fallbacks

    async def generate(self, schema: type[T], prompt: str, *, effort: str | None = None) -> T:
        extra: dict = {}
        if self.use_fallbacks:
            extra = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
        async with self.client.beta.messages.stream(
            model=self.model,
            max_tokens=self.max_tokens,
            system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": prompt}],
            thinking={"type": "adaptive"},
            output_config={"effort": effort or self.effort},
            output_format=schema,
            **extra,
        ) as stream:
            message = await stream.get_final_message()

        if message.stop_reason == "refusal":
            category = message.stop_details.category if message.stop_details else None
            raise GenerationError(f"Request declined (category={category}) for {schema.__name__}")
        if message.stop_reason == "max_tokens":
            raise GenerationError(f"Output truncated at max_tokens for {schema.__name__}")
        parsed = message.parsed_output
        if parsed is None:
            raise GenerationError(f"No parsable {schema.__name__} in response")
        return parsed
