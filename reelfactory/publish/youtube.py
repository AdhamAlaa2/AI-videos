"""YouTube Shorts via the YouTube Data API v3 resumable upload.

Credentials (OAuth, scope youtube.upload): YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN.
Get a refresh token once with `reelfactory auth youtube`.
"""

from __future__ import annotations

import http.server
import threading
import urllib.parse
import webbrowser
from pathlib import Path

import httpx

from .base import PostText, PublishError, PublishResult, env

TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
SCOPE = "https://www.googleapis.com/auth/youtube.upload"


class YouTubePublisher:
    platform = "youtube"

    def __init__(self, http: httpx.Client | None = None, category_id: str = "27") -> None:  # 27 = Education
        self.http = http or httpx.Client(timeout=600)
        self.category_id = category_id

    def _access_token(self) -> str:
        r = self.http.post(
            TOKEN_URL,
            data={
                "client_id": env("YT_CLIENT_ID"),
                "client_secret": env("YT_CLIENT_SECRET"),
                "refresh_token": env("YT_REFRESH_TOKEN"),
                "grant_type": "refresh_token",
            },
        )
        if r.status_code != 200:
            raise PublishError(f"YouTube token refresh failed: {r.text}")
        return r.json()["access_token"]

    def publish(self, video: Path, text: PostText, public: bool) -> PublishResult:
        token = self._access_token()
        title = text.title if "#shorts" in text.title.lower() else f"{text.title} #Shorts"
        if len(title) > 100:
            title = text.title[:100]
        body = {
            "snippet": {
                "title": title,
                "description": text.with_tags(max_chars=4900) + "\n\n#Shorts",
                "tags": [h.lstrip("#") for h in text.hashtags][:30],
                "categoryId": self.category_id,
            },
            "status": {
                "privacyStatus": "public" if public else "private",
                "selfDeclaredMadeForKids": False,
                "containsSyntheticMedia": True,  # disclose AI-generated visuals/voice
            },
        }
        size = video.stat().st_size
        init = self.http.post(
            UPLOAD_URL,
            params={"uploadType": "resumable", "part": "snippet,status"},
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Length": str(size),
                "X-Upload-Content-Type": "video/mp4",
            },
            json=body,
        )
        if init.status_code != 200 or "location" not in init.headers:
            raise PublishError(f"YouTube upload init failed: {init.status_code} {init.text}")
        session = init.headers["location"]

        up = self.http.put(
            session,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "video/mp4", "Content-Length": str(size)},
            content=video.read_bytes(),
        )
        if up.status_code not in (200, 201):
            raise PublishError(f"YouTube upload failed: {up.status_code} {up.text}")
        vid = up.json()["id"]
        return PublishResult(self.platform, True, vid, f"https://youtube.com/shorts/{vid}", body["status"]["privacyStatus"])


def authorize(client_id: str, client_secret: str, port: int = 8765) -> str:
    """One-time OAuth consent in the browser (loopback flow). Returns a refresh token."""
    redirect = f"http://127.0.0.1:{port}"
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect,
            "response_type": "code",
            "scope": SCOPE,
            "access_type": "offline",
            "prompt": "consent",
        }
    )
    got: dict[str, str] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            got.update({k: v[0] for k, v in q.items()})
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Authorized. You can close this tab.")

        def log_message(self, *a):
            pass

    server = http.server.HTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.handle_request)
    thread.start()
    print(f"Open this URL to authorize YouTube uploads:\n{url}")
    webbrowser.open(url)
    thread.join()
    server.server_close()
    if "code" not in got:
        raise PublishError(f"Authorization failed: {got}")
    r = httpx.post(
        TOKEN_URL,
        data={
            "code": got["code"],
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect,
            "grant_type": "authorization_code",
        },
    )
    r.raise_for_status()
    return r.json()["refresh_token"]
