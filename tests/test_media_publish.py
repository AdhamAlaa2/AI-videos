import base64
import json
from pathlib import Path

import httpx
import pytest

from reelfactory.media import ffmpeg
from reelfactory.media.captions import TimedWord, PunchCard, build_ass
from reelfactory.media.produce import apply_variant, produce
from reelfactory.media.tts import ElevenLabsTTS, SilentTTS, words_from_alignment
from reelfactory.media.visuals import FalClient, FalVisuals, PlaceholderVisuals
from reelfactory.models import Beat, Reel
from reelfactory.publish import PublishError, post_text
from reelfactory.publish.meta import FacebookPublisher, InstagramPublisher
from reelfactory.publish.tiktok import TikTokPublisher
from reelfactory.publish.youtube import YouTubePublisher

EXAMPLE = next(Path(__file__).parent.parent.joinpath("examples").glob("*.json"))


@pytest.fixture
def reel() -> Reel:
    return Reel.model_validate_json(EXAMPLE.read_text(encoding="utf-8"))


@pytest.fixture
def short_reel(reel) -> Reel:
    """A 6-second cut of the example so real ffmpeg rendering stays fast."""
    r = reel.model_copy(deep=True)
    r.length_sec = 6
    hook, cta = r.script.beats[0], r.script.beats[-1]
    r.script.beats = [hook, Beat(**{**cta.model_dump(), "start_sec": 2.0, "end_sec": 6.0})]
    s1, s2 = r.visuals.scenes[0], r.visuals.scenes[1]
    r.visuals.scenes = [s1, s2.model_copy(update={"scene_number": 2, "start_sec": 2.0, "duration_sec": 4.0})]
    return r


def mock(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


# ------------------------------------------------------------------ captions / tts


def test_alignment_grouped_into_words():
    chars = list("Hi there")
    starts = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7]
    ends = [s + 0.1 for s in starts]
    words = words_from_alignment(chars, starts, ends)
    assert [(w.text, w.start, round(w.end, 2)) for w in words] == [("Hi", 0.0, 0.2), ("there", 0.3, 0.8)]


def test_ass_highlights_one_word_at_a_time():
    words = [TimedWord(t, i * 0.5, i * 0.5 + 0.4) for i, t in enumerate("one two three four".split())]
    ass = build_ass(words, [PunchCard("BIG {CARD}", 0, 2)])
    dialogue = [l for l in ass.splitlines() if l.startswith("Dialogue: 0")]
    assert len(dialogue) == 4
    assert dialogue[0].count("\\c&H0000E6FF") == 1
    assert "BIG (CARD)" in ass  # braces escaped so libass doesn't treat them as tags


def test_variant_swaps_hook_cta_and_title(reel):
    b = apply_variant(reel, "B")
    v = next(x for x in reel.ab_test.variants if x.label == "B")
    assert b.script.beats[0].voiceover == v.hook
    assert b.script.beats[-1].voiceover == v.cta
    assert b.title == v.title
    assert reel.script.beats[0].voiceover != v.hook  # original untouched


def test_elevenlabs_request_and_alignment(tmp_path):
    mp3 = tmp_path / "t.mp3"
    ffmpeg.run("-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-c:a", "libmp3lame", mp3)
    seen = {}

    def handler(req: httpx.Request):
        seen["url"], seen["key"], seen["body"] = str(req.url), req.headers["xi-api-key"], json.loads(req.content)
        return httpx.Response(200, json={
            "audio_base64": base64.b64encode(mp3.read_bytes()).decode(),
            "alignment": {"characters": list("go now"), "character_start_times_seconds": [0, .1, .2, .3, .4, .5],
                          "character_end_times_seconds": [.1, .2, .3, .4, .5, .6]},
        })

    tts = ElevenLabsTTS(api_key="k", voice_id="v1", http=mock(handler))
    clip = tts.synthesize("go now", "ar", tmp_path / "vo.wav")
    assert seen["url"].endswith("/v1/text-to-speech/v1/with-timestamps")
    assert seen["key"] == "k" and seen["body"]["model_id"] == "eleven_multilingual_v2"
    assert [w.text for w in clip.words] == ["go", "now"]
    assert 0.9 < clip.duration < 1.2


# ------------------------------------------------------------------ fal


def test_fal_image_then_video(tmp_path, short_reel):
    calls = []

    def handler(req: httpx.Request):
        u = str(req.url)
        calls.append((req.method, u))
        assert req.headers.get("authorization", "Key k") == "Key k"
        if req.method == "POST":
            model = u.split("queue.fal.run/")[1]
            base = f"https://queue.fal.run/{model}/requests/r1"
            return httpx.Response(200, json={"request_id": "r1", "status_url": base + "/status", "response_url": base})
        if u.endswith("/status"):
            return httpx.Response(200, json={"status": "COMPLETED"})
        if "kling" in u and u.endswith("/r1"):
            return httpx.Response(200, json={"video": {"url": "https://cdn/v.mp4"}})
        if u.endswith("/r1"):
            return httpx.Response(200, json={"images": [{"url": "https://cdn/i.jpg"}]})
        return httpx.Response(200, content=b"bytes")

    vis = FalVisuals(FalClient(api_key="k", http=mock(handler), poll_sec=0))
    scene = short_reel.visuals.scenes[0]
    vis.image(scene, "style", 42, tmp_path / "s.jpg")
    assert vis.last_image_url == "https://cdn/i.jpg"
    vis.video(scene, tmp_path / "s.jpg", vis.last_image_url, tmp_path / "s.mp4")
    posts = [u for m, u in calls if m == "POST"]
    assert posts[0].endswith("fal-ai/flux-pro/v1.1") and "kling-video" in posts[1]
    assert (tmp_path / "s.mp4").read_bytes() == b"bytes"


# ------------------------------------------------------------------ real render (offline providers)


def test_draft_render_produces_exact_length_vertical_mp4(tmp_path, short_reel):
    import imageio_ffmpeg

    res = produce(short_reel, tmp_path / "w", SilentTTS(), PlaceholderVisuals())
    frames, secs = imageio_ffmpeg.count_frames_and_secs(str(res.video))
    assert abs(secs - 6.0) < 0.1 and frames == 180
    meta = imageio_ffmpeg.read_frames(str(res.video))
    assert next(meta)["size"] == (1080, 1920)
    assert "Dialogue:" in res.captions.read_text()
    # second run reuses cached assets
    mtime = (tmp_path / "w" / "clip_01.mp4").stat().st_mtime
    produce(short_reel, tmp_path / "w", SilentTTS(), PlaceholderVisuals())
    assert (tmp_path / "w" / "clip_01.mp4").stat().st_mtime == mtime


# ------------------------------------------------------------------ publishers


@pytest.fixture
def video(tmp_path) -> Path:
    p = tmp_path / "v.mp4"
    p.write_bytes(b"\x00" * 1000)
    return p


def test_post_text_uses_variant(reel):
    t = post_text(reel, "C")
    assert t.title == next(v.title for v in reel.ab_test.variants if v.label == "C")
    assert t.with_tags(limit=5).count("#") == 5


def test_youtube_private_upload_with_ai_disclosure(monkeypatch, video, reel):
    for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"):
        monkeypatch.setenv(k, "x")
    seen = {}

    def handler(req: httpx.Request):
        u = str(req.url)
        if u.startswith("https://oauth2.googleapis.com/token"):
            return httpx.Response(200, json={"access_token": "AT"})
        if req.method == "POST":
            seen["meta"] = json.loads(req.content)
            assert req.url.params["uploadType"] == "resumable"
            assert req.headers["X-Upload-Content-Length"] == "1000"
            return httpx.Response(200, headers={"Location": "https://upload/session"})
        assert u == "https://upload/session" and req.headers["authorization"] == "Bearer AT"
        return httpx.Response(200, json={"id": "abc"})

    res = YouTubePublisher(http=mock(handler)).publish(video, post_text(reel), public=False)
    assert res.ok and res.url == "https://youtube.com/shorts/abc"
    assert seen["meta"]["status"]["privacyStatus"] == "private"
    assert seen["meta"]["status"]["containsSyntheticMedia"] is True
    assert "#Shorts" in seen["meta"]["snippet"]["title"]


def test_tiktok_flow(monkeypatch, video, reel):
    monkeypatch.setenv("TIKTOK_ACCESS_TOKEN", "T")
    seen = {}

    def handler(req: httpx.Request):
        u = str(req.url)
        ok = {"error": {"code": "ok"}}
        if u.endswith("creator_info/query/"):
            return httpx.Response(200, json={"data": {"privacy_level_options": ["SELF_ONLY", "PUBLIC_TO_EVERYONE"]}, **ok})
        if u.endswith("video/init/"):
            seen["init"] = json.loads(req.content)
            return httpx.Response(200, json={"data": {"publish_id": "p1", "upload_url": "https://up/tt"}, **ok})
        if u == "https://up/tt":
            seen["range"] = req.headers["content-range"]
            return httpx.Response(201)
        if u.endswith("status/fetch/"):
            return httpx.Response(200, json={"data": {"status": "PUBLISH_COMPLETE"}, **ok})
        raise AssertionError(u)

    res = TikTokPublisher(http=mock(handler), poll_sec=0).publish(video, post_text(reel), public=False)
    assert res.ok and res.post_id == "p1"
    assert seen["init"]["post_info"]["privacy_level"] == "SELF_ONLY"
    assert seen["init"]["post_info"]["is_aigc"] is True
    assert seen["init"]["source_info"] == {"source": "FILE_UPLOAD", "video_size": 1000, "chunk_size": 1000, "total_chunk_count": 1}
    assert seen["range"] == "bytes 0-999/1000"


def test_tiktok_refuses_public_when_not_allowed(monkeypatch, video, reel):
    monkeypatch.setenv("TIKTOK_ACCESS_TOKEN", "T")
    client = mock(lambda req: httpx.Response(200, json={"data": {"privacy_level_options": ["SELF_ONLY"]}, "error": {"code": "ok"}}))
    with pytest.raises(PublishError, match="does not allow PUBLIC"):
        TikTokPublisher(http=client).publish(video, post_text(reel), public=True)


def test_instagram_needs_public(video, reel):
    res = InstagramPublisher(http=mock(lambda r: httpx.Response(500))).publish(video, post_text(reel), public=False)
    assert not res.ok and "skipped" in res.detail


def test_instagram_resumable_flow(monkeypatch, video, reel):
    monkeypatch.setenv("IG_USER_ID", "IG1")
    monkeypatch.setenv("IG_ACCESS_TOKEN", "TOK")
    steps = []

    def handler(req: httpx.Request):
        u = str(req.url)
        steps.append(u.split("?")[0])
        if u.endswith("/IG1/media"):
            body = dict(x.split("=", 1) for x in req.content.decode().split("&"))
            assert body["media_type"] == "REELS" and body["upload_type"] == "resumable"
            return httpx.Response(200, json={"id": "C1", "uri": "https://rupload.facebook.com/ig-api-upload/v25.0/C1"})
        if "rupload" in u:
            assert req.headers["authorization"] == "OAuth TOK" and req.headers["file_size"] == "1000"
            return httpx.Response(200, json={"success": True})
        if "/C1" in u and req.method == "GET":
            return httpx.Response(200, json={"status_code": "FINISHED"})
        if u.endswith("/media_publish"):
            return httpx.Response(200, json={"id": "M1"})
        raise AssertionError(u)

    res = InstagramPublisher(http=mock(handler), poll_sec=0).publish(video, post_text(reel), public=True)
    assert res.ok and res.post_id == "M1"
    assert steps[-1].endswith("/media_publish")


def test_facebook_private_is_draft(monkeypatch, video, reel):
    monkeypatch.setenv("FB_PAGE_ID", "PG")
    monkeypatch.setenv("FB_PAGE_ACCESS_TOKEN", "TOK")
    finish = {}

    def handler(req: httpx.Request):
        u = str(req.url)
        if "rupload" in u:
            return httpx.Response(200, json={"success": True})
        body = dict(x.split("=", 1) for x in req.content.decode().split("&"))
        if body["upload_phase"] == "start":
            return httpx.Response(200, json={"video_id": "V9", "upload_url": "https://rupload.facebook.com/video-upload/v25.0/V9"})
        finish.update(body)
        return httpx.Response(200, json={"success": True})

    res = FacebookPublisher(http=mock(handler)).publish(video, post_text(reel), public=False)
    assert res.ok and res.detail == "DRAFT" and finish["video_state"] == "DRAFT"


def test_missing_credentials_raise(monkeypatch, video, reel):
    monkeypatch.delenv("TIKTOK_ACCESS_TOKEN", raising=False)
    with pytest.raises(PublishError, match="TIKTOK_ACCESS_TOKEN"):
        TikTokPublisher(http=mock(lambda r: httpx.Response(500))).publish(video, post_text(reel), public=False)
