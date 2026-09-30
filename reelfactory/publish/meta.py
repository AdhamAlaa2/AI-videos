"""Instagram Reels and Facebook Page Reels via the Meta Graph API (resumable upload, no public URL needed).

Instagram: IG_USER_ID + IG_ACCESS_TOKEN (Business/Creator account, instagram_content_publish).
    IG_GRAPH_HOST defaults to graph.facebook.com (Facebook Login); use graph.instagram.com for
    Instagram Login tokens.
Facebook:  FB_PAGE_ID + FB_PAGE_ACCESS_TOKEN (pages_manage_posts, publish_video).
Graph version: META_GRAPH_VERSION (default v25.0).
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx

from .base import GRAPH_VERSION, PostText, PublishError, PublishResult, env, poll


def _check(r: httpx.Response, what: str) -> dict:
    try:
        data = r.json()
    except ValueError:
        data = {}
    if r.status_code >= 400 or "error" in data:
        raise PublishError(f"{what} failed: {r.status_code} {data.get('error') or r.text}")
    return data


def _rupload(http: httpx.Client, url: str, token: str, video: Path) -> None:
    size = video.stat().st_size
    r = http.post(
        url,
        headers={"Authorization": f"OAuth {token}", "offset": "0", "file_size": str(size)},
        content=video.read_bytes(),
    )
    _check(r, "video upload")


class InstagramPublisher:
    """Instagram has no private/draft mode via the API, so this only posts when public=True."""

    platform = "instagram"

    def __init__(self, http: httpx.Client | None = None, poll_sec: float = 10, timeout_sec: float = 600) -> None:
        self.http = http or httpx.Client(timeout=600)
        self.poll_sec = poll_sec
        self.timeout_sec = timeout_sec

    def publish(self, video: Path, text: PostText, public: bool) -> PublishResult:
        if not public:
            return PublishResult(self.platform, False, detail="skipped: Instagram has no private mode; pass --public to post")
        ig, token = env("IG_USER_ID"), env("IG_ACCESS_TOKEN")
        graph = f"https://{os.environ.get('IG_GRAPH_HOST', 'graph.facebook.com')}/{GRAPH_VERSION}"

        container = _check(
            self.http.post(
                f"{graph}/{ig}/media",
                data={
                    "media_type": "REELS",
                    "upload_type": "resumable",
                    "caption": text.with_tags(limit=30, max_chars=2200),
                    "share_to_feed": "true",
                    "access_token": token,
                },
            ),
            "Instagram container",
        )
        cid = container["id"]
        upload_uri = container.get("uri") or f"https://rupload.facebook.com/ig-api-upload/{GRAPH_VERSION}/{cid}"
        _rupload(self.http, upload_uri, token, video)

        def ready() -> str | None:
            st = _check(self.http.get(f"{graph}/{cid}", params={"fields": "status_code", "access_token": token}), "status")
            code = st.get("status_code")
            if code in ("ERROR", "EXPIRED"):
                raise PublishError(f"Instagram processing {code}")
            return code if code == "FINISHED" else None

        poll(ready, self.poll_sec, self.timeout_sec, "Instagram processing")
        pub = _check(
            self.http.post(f"{graph}/{ig}/media_publish", data={"creation_id": cid, "access_token": token}),
            "Instagram publish",
        )
        return PublishResult(self.platform, True, pub["id"], "", "published")


class FacebookPublisher:
    """Facebook Page Reels. Private runs are saved as DRAFT; public runs are PUBLISHED."""

    platform = "facebook"

    def __init__(self, http: httpx.Client | None = None) -> None:
        self.http = http or httpx.Client(timeout=600)

    def publish(self, video: Path, text: PostText, public: bool) -> PublishResult:
        page, token = env("FB_PAGE_ID"), env("FB_PAGE_ACCESS_TOKEN")
        graph = f"https://graph.facebook.com/{GRAPH_VERSION}/{page}/video_reels"
        start = _check(self.http.post(graph, data={"upload_phase": "start", "access_token": token}), "Facebook start")
        vid = start["video_id"]
        upload_url = start.get("upload_url") or f"https://rupload.facebook.com/video-upload/{GRAPH_VERSION}/{vid}"
        _rupload(self.http, upload_url, token, video)
        state = "PUBLISHED" if public else "DRAFT"
        _check(
            self.http.post(
                graph,
                data={
                    "upload_phase": "finish",
                    "video_id": vid,
                    "video_state": state,
                    "title": text.title,
                    "description": text.with_tags(),
                    "access_token": token,
                },
            ),
            "Facebook finish",
        )
        return PublishResult(self.platform, True, vid, f"https://www.facebook.com/reel/{vid}", state)
