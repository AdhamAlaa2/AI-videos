"""Shared publishing types and post-text building."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from ..models import Reel

GRAPH_VERSION = os.environ.get("META_GRAPH_VERSION", "v25.0")


@dataclass
class PostText:
    title: str
    caption: str
    hashtags: list[str]

    def with_tags(self, limit: int | None = None, max_chars: int | None = None) -> str:
        tags = self.hashtags[:limit] if limit else self.hashtags
        text = f"{self.caption}\n\n{' '.join(tags)}".strip()
        return text[:max_chars] if max_chars else text


@dataclass
class PublishResult:
    platform: str
    ok: bool
    post_id: str = ""
    url: str = ""
    detail: str = ""


class Publisher(Protocol):
    platform: str

    def publish(self, video: Path, text: PostText, public: bool) -> PublishResult: ...


class PublishError(RuntimeError):
    pass


def post_text(reel: Reel, variant: str | None = None, caption_index: int = 0) -> PostText:
    """Title/caption from the chosen A/B/C variant (default: the reel's own title)."""
    title = reel.title
    if variant:
        v = next((x for x in reel.ab_test.variants if x.label == variant), None)
        if v is None:
            raise ValueError(f"Reel has no variant {variant!r}")
        title = v.title
    caps = reel.packaging.captions
    caption = caps[caption_index % len(caps)] if caps else title
    return PostText(title=title, caption=caption, hashtags=list(reel.packaging.hashtags))


def env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise PublishError(f"{name} is not set")
    return value


def poll(check: Callable[[], str | None], every: float, timeout: float, what: str) -> str:
    """Call `check` until it returns a terminal value; raise on timeout."""
    deadline = time.monotonic() + timeout
    while True:
        result = check()
        if result is not None:
            return result
        if time.monotonic() > deadline:
            raise PublishError(f"timed out waiting for {what}")
        time.sleep(every)
