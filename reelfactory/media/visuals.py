"""Scene visuals: placeholder storyboard frames, AI stills, or AI video clips.

Every provider returns a still image; `FalVideo` also returns a motion clip. Stills are animated
with a Ken Burns move during assembly, so the cheaper modes still produce a moving reel.
"""

from __future__ import annotations

import os
import textwrap
import time
from pathlib import Path
from typing import Protocol

import httpx

from ..models import Scene

W, H = 1080, 1920


class Visuals(Protocol):
    name: str

    def image(self, scene: Scene, style: str, seed: int, dst: Path) -> Path: ...

    def video(self, scene: Scene, image: Path, image_url: str | None, dst: Path) -> Path | None: ...


def _font(size: int):
    from PIL import ImageFont

    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
    ):
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


class PlaceholderVisuals:
    """Offline storyboard frames: scene number, section and visual description on a gradient."""

    name = "placeholder"
    PALETTE = [(24, 38, 62), (62, 30, 24), (20, 54, 44), (54, 24, 58), (58, 48, 20)]

    def image(self, scene: Scene, style: str, seed: int, dst: Path) -> Path:
        from PIL import Image, ImageDraw

        top = self.PALETTE[scene.scene_number % len(self.PALETTE)]
        img = Image.new("RGB", (W, H))
        d = ImageDraw.Draw(img)
        for y in range(H):
            k = y / H
            d.line([(0, y), (W, y)], fill=tuple(int(c * (1 - k) + 8 * k) for c in top))
        # Text sits in the centre band: clear of the caption layers and inside the Ken Burns crop.
        d.text((140, 760), f"SCENE {scene.scene_number}", font=_font(88), fill=(255, 214, 0))
        d.text((140, 870), f"{scene.section} · {scene.duration_sec:g}s", font=_font(40), fill=(200, 200, 200))
        y = 950
        for line in textwrap.wrap(scene.visual_description, 26)[:6]:
            d.text((140, y), line, font=_font(52), fill=(255, 255, 255))
            y += 68
        img.save(dst, quality=92)
        return dst

    def video(self, scene: Scene, image: Path, image_url: str | None, dst: Path) -> Path | None:
        return None


class FalClient:
    """Minimal client for fal.ai's queue API (submit -> poll status -> fetch result)."""

    def __init__(self, api_key: str | None = None, http: httpx.Client | None = None, poll_sec: float = 3.0, timeout_sec: float = 900):
        self.key = api_key or os.environ.get("FAL_KEY", "")
        if not self.key:
            raise ValueError("FAL_KEY is not set")
        self.http = http or httpx.Client(timeout=120, follow_redirects=True)
        self.poll_sec = poll_sec
        self.timeout_sec = timeout_sec

    @property
    def _h(self) -> dict[str, str]:
        return {"Authorization": f"Key {self.key}", "Content-Type": "application/json"}

    def run(self, model: str, payload: dict) -> dict:
        r = self.http.post(f"https://queue.fal.run/{model}", headers=self._h, json=payload)
        r.raise_for_status()
        sub = r.json()
        status_url, response_url = sub["status_url"], sub["response_url"]
        deadline = time.monotonic() + self.timeout_sec
        while True:
            s = self.http.get(status_url, headers=self._h)
            s.raise_for_status()
            st = s.json()
            if st.get("status") == "COMPLETED":
                if st.get("error"):
                    raise RuntimeError(f"fal {model} failed: {st['error']}")
                break
            if time.monotonic() > deadline:
                raise TimeoutError(f"fal {model} timed out ({sub.get('request_id')})")
            time.sleep(self.poll_sec)
        res = self.http.get(response_url, headers=self._h)
        res.raise_for_status()
        return res.json()

    def download(self, url: str, dst: Path) -> Path:
        with self.http.stream("GET", url) as r:
            r.raise_for_status()
            with open(dst, "wb") as f:
                for chunk in r.iter_bytes():
                    f.write(chunk)
        return dst


class FalVisuals:
    """AI stills via FLUX, optionally animated via an image-to-video model (default Kling 2.6 Pro).

    Model ids and the video model's image field are configurable because fal's catalogue changes
    often: FAL_IMAGE_MODEL, FAL_VIDEO_MODEL, FAL_VIDEO_IMAGE_FIELD.
    """

    name = "fal"

    def __init__(self, client: FalClient | None = None, animate: bool = True) -> None:
        self.fal = client or FalClient()
        self.animate = animate
        self.image_model = os.environ.get("FAL_IMAGE_MODEL", "fal-ai/flux-pro/v1.1")
        self.video_model = os.environ.get("FAL_VIDEO_MODEL", "fal-ai/kling-video/v2.6/pro/image-to-video")
        self.video_image_field = os.environ.get("FAL_VIDEO_IMAGE_FIELD", "start_image_url")
        self.last_image_url: str | None = None

    def image(self, scene: Scene, style: str, seed: int, dst: Path) -> Path:
        out = self.fal.run(
            self.image_model,
            {
                "prompt": f"{scene.image_prompt}. Style: {style}",
                "image_size": "portrait_16_9",
                "num_images": 1,
                "seed": seed,
                "output_format": "jpeg",
                "safety_tolerance": "2",
            },
        )
        self.last_image_url = out["images"][0]["url"]
        return self.fal.download(self.last_image_url, dst)

    def video(self, scene: Scene, image: Path, image_url: str | None, dst: Path) -> Path | None:
        if not self.animate or not image_url:
            return None
        out = self.fal.run(
            self.video_model,
            {
                "prompt": scene.video_prompt,
                self.video_image_field: image_url,
                "duration": "5",  # shortest supported clip; trimmed to the scene length in assembly
                "negative_prompt": scene.negative_prompt,
                "generate_audio": False,  # our own voice-over, music and captions go on top
            },
        )
        return self.fal.download(out["video"]["url"], dst)
