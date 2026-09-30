"""TikTok via the Content Posting API (Direct Post, FILE_UPLOAD).

Credentials: TIKTOK_ACCESS_TOKEN - a user access token with the `video.publish` scope from your
TikTok developer app. Until TikTok audits the app, every post is forced to private (SELF_ONLY).
"""

from __future__ import annotations

from pathlib import Path

import httpx

from .base import PostText, PublishError, PublishResult, env, poll

API = "https://open.tiktokapis.com/v2/post/publish"
CHUNK = 10 * 1024 * 1024  # TikTok chunks: 5-64 MB, last chunk may be up to 128 MB


class TikTokPublisher:
    platform = "tiktok"

    def __init__(self, http: httpx.Client | None = None, poll_sec: float = 5, timeout_sec: float = 600) -> None:
        self.http = http or httpx.Client(timeout=300)
        self.poll_sec = poll_sec
        self.timeout_sec = timeout_sec

    def _post(self, path: str, token: str, body: dict) -> dict:
        r = self.http.post(
            f"{API}/{path}",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"},
            json=body,
        )
        data = r.json()
        err = data.get("error", {})
        if r.status_code != 200 or err.get("code") not in (None, "ok"):
            raise PublishError(f"TikTok {path} failed: {r.status_code} {err or r.text}")
        return data["data"]

    def publish(self, video: Path, text: PostText, public: bool) -> PublishResult:
        token = env("TIKTOK_ACCESS_TOKEN")
        creator = self._post("creator_info/query/", token, {})
        options = creator.get("privacy_level_options", [])
        privacy = "PUBLIC_TO_EVERYONE" if public else "SELF_ONLY"
        if privacy not in options:
            raise PublishError(f"TikTok account does not allow {privacy}; allowed: {options}")

        size = video.stat().st_size
        chunk = size if size <= 64 * 1024 * 1024 else CHUNK
        count = max(1, size // chunk)  # remainder rides on the last chunk, per TikTok's rules
        init = self._post(
            "video/init/",
            token,
            {
                "post_info": {
                    "title": text.with_tags(max_chars=2200),
                    "privacy_level": privacy,
                    "disable_duet": False,
                    "disable_stitch": False,
                    "disable_comment": False,
                    "video_cover_timestamp_ms": 1000,
                    "is_aigc": True,  # AI-generated content label
                },
                "source_info": {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": chunk, "total_chunk_count": count},
            },
        )
        publish_id, upload_url = init["publish_id"], init["upload_url"]

        with open(video, "rb") as f:
            for i in range(count):
                start = i * chunk
                end = size - 1 if i == count - 1 else start + chunk - 1
                f.seek(start)
                data = f.read(end - start + 1)
                r = self.http.put(
                    upload_url,
                    headers={
                        "Content-Type": "video/mp4",
                        "Content-Length": str(len(data)),
                        "Content-Range": f"bytes {start}-{end}/{size}",
                    },
                    content=data,
                )
                if r.status_code not in (200, 201, 206):
                    raise PublishError(f"TikTok chunk {i + 1}/{count} failed: {r.status_code} {r.text}")

        def check() -> str | None:
            st = self._post("status/fetch/", token, {"publish_id": publish_id})
            status = st.get("status")
            if status == "FAILED":
                raise PublishError(f"TikTok publish failed: {st.get('fail_reason')}")
            return status if status in ("PUBLISH_COMPLETE", "SEND_TO_USER_INBOX") else None

        status = poll(check, self.poll_sec, self.timeout_sec, "TikTok processing")
        return PublishResult(self.platform, True, publish_id, "", f"{status} ({privacy})")

