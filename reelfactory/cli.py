"""Command line entry point.

    reelfactory run --niches History,Space --language en --length 45 --ideas 100 --keep 3
    reelfactory render examples/ANC-EN-5F6766.json
    reelfactory produce examples/ANC-EN-5F6766.json --mode draft
    reelfactory publish examples/ANC-EN-5F6766.json --platforms youtube,tiktok
    reelfactory auth youtube
    reelfactory niches
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from .config import LANGUAGES, LENGTHS, NICHES, RunConfig
from .models import Reel
from .render import to_markdown


def _write(reel: Reel, out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{reel.reel_id}.json").write_text(reel.model_dump_json(indent=2), encoding="utf-8")
    md = out / f"{reel.reel_id}.md"
    md.write_text(to_markdown(reel), encoding="utf-8")
    return md


def _past_titles(out: Path) -> list[str]:
    titles = []
    for f in sorted(out.glob("*.json")):
        try:
            titles.append(json.loads(f.read_text(encoding="utf-8"))["idea"]["working_title"])
        except (KeyError, ValueError):
            continue
    return titles


def _produce(reel: Reel, json_path: Path, mode: str, music: str | None, variant: str | None) -> Path:
    from .media import produce, providers

    tts, visuals = providers(mode)
    res = produce(reel, json_path.parent / reel.reel_id, tts, visuals, Path(music) if music else None, variant)
    for w in res.warnings:
        print(f"  warning: {w}")
    return res.video


def _publish(reel: Reel, video: Path, platforms: list[str], public: bool, variant: str | None) -> list:
    from .publish import PUBLISHERS, PublishError, PublishResult, post_text

    text = post_text(reel, variant)
    results = []
    for name in platforms:
        if name not in PUBLISHERS:
            raise SystemExit(f"Unknown platform {name!r}; choose from {', '.join(PUBLISHERS)}")
        try:
            res = PUBLISHERS[name]().publish(video, text, public)
        except (PublishError, OSError) as e:
            res = PublishResult(name, False, detail=str(e))
        except Exception as e:  # HTTP/transport errors: report and keep going with other platforms
            res = PublishResult(name, False, detail=f"{type(e).__name__}: {e}")
        print(f"  {name:<10} {'OK ' if res.ok else 'FAIL'} {res.post_id} {res.url} {res.detail}".rstrip())
        results.append(res)
    log = video.parent / "published.json"
    history = json.loads(log.read_text()) if log.exists() else []
    history += [{**r.__dict__, "video": str(video), "variant": variant, "public": public} for r in results]
    log.write_text(json.dumps(history, indent=2, ensure_ascii=False))
    return results


def cmd_run(a: argparse.Namespace) -> int:
    from .llm import ClaudeLLM
    from .pipeline import Factory

    if a.publish and not a.produce:
        raise SystemExit("--publish needs --produce (draft, stills or full)")
    niches = [n.strip() for n in a.niches.split(",")] if a.niches else list(NICHES)
    out = Path(a.out)
    for lang in a.language.split(","):
        cfg = RunConfig(
            niches=niches,
            language=lang.strip(),
            length_sec=a.length,
            ideas=a.ideas,
            keep=a.keep,
            model=a.model,
            effort=a.effort,
        )
        factory = Factory(ClaudeLLM(model=cfg.model, effort=cfg.effort), cfg, avoid_titles=_past_titles(out))
        result = asyncio.run(factory.run_cycle())
        print(f"[{cfg.language}] {len(result.ideas)} ideas -> {len(result.shipped)} shipped, {len(result.rejected)} rejected")
        for reel in result.shipped:
            md = _write(reel, out)
            print(f"  {reel.virality_score:>5}  {md}")
            if a.produce:
                video = _produce(reel, md.with_suffix(".json"), a.produce, a.music, None)
                print(f"         video: {video}")
                if a.publish:
                    _publish(reel, video, a.publish.split(","), a.public, None)
        for title, why in result.rejected:
            print(f"  rejected: {title} - {why}")
    return 0


def cmd_render(a: argparse.Namespace) -> int:
    for path in a.files:
        reel = Reel.model_validate_json(Path(path).read_text(encoding="utf-8"))
        md = Path(path).with_suffix(".md")
        md.write_text(to_markdown(reel), encoding="utf-8")
        print(md)
    return 0


def _video_path(json_path: Path, reel: Reel, variant: str | None) -> Path:
    return json_path.parent / reel.reel_id / f"{reel.reel_id}{'-' + variant if variant else ''}.mp4"


def cmd_produce(a: argparse.Namespace) -> int:
    for path in map(Path, a.files):
        reel = Reel.model_validate_json(path.read_text(encoding="utf-8"))
        print(_produce(reel, path, a.mode, a.music, a.variant))
    return 0


def cmd_publish(a: argparse.Namespace) -> int:
    path = Path(a.file)
    reel = Reel.model_validate_json(path.read_text(encoding="utf-8"))
    video = Path(a.video) if a.video else _video_path(path, reel, a.variant)
    if not video.exists():
        raise SystemExit(f"{video} not found - run `reelfactory produce {path}` first")
    results = _publish(reel, video, a.platforms.split(","), a.public, a.variant)
    return 0 if all(r.ok for r in results) else 1


def cmd_auth(a: argparse.Namespace) -> int:
    import os

    from .publish.youtube import authorize

    token = authorize(os.environ["YT_CLIENT_ID"], os.environ["YT_CLIENT_SECRET"])
    print(f"\nexport YT_REFRESH_TOKEN={token}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="reelfactory", description="Viral short-form video factory.")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="Run one production cycle.")
    r.add_argument("--niches", help="Comma-separated; default: all 30.")
    r.add_argument("--language", default="en", help=f"Comma-separated from {','.join(LANGUAGES)}")
    r.add_argument("--length", type=int, default=45, choices=LENGTHS)
    r.add_argument("--ideas", type=int, default=100)
    r.add_argument("--keep", type=int, default=3, help="Reels to ship per language.")
    r.add_argument("--model", default="claude-opus-5-5")
    r.add_argument("--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"])
    r.add_argument("--out", default="output")
    r.add_argument("--produce", choices=["draft", "stills", "full"], help="Also render each shipped reel to MP4.")
    r.add_argument("--music", help="Music bed (audio file) for rendered reels.")
    r.add_argument("--publish", help="Comma-separated platforms to post rendered reels to (needs --produce).")
    r.add_argument("--public", action="store_true", help="Post publicly (default: private/draft where supported).")
    r.set_defaults(fn=cmd_run)

    pr = sub.add_parser("produce", help="Render reel JSON files to finished MP4s.")
    pr.add_argument("files", nargs="+")
    pr.add_argument(
        "--mode", default="draft", choices=["draft", "stills", "full"],
        help="draft: offline storyboard + silent VO. stills: AI images + AI voice. full: AI video clips + AI voice.",
    )
    pr.add_argument("--music", help="Music bed (audio file); ducked under the voice-over.")
    pr.add_argument("--variant", choices=["A", "B", "C"], help="Render an A/B/C variant's hook and CTA.")
    pr.set_defaults(fn=cmd_produce)

    pb = sub.add_parser("publish", help="Upload a produced reel to platforms.")
    pb.add_argument("file", help="Reel JSON")
    pb.add_argument("--platforms", required=True, help="Comma-separated: youtube,tiktok,instagram,facebook")
    pb.add_argument("--video", help="MP4 to upload (default: the produced video next to the JSON).")
    pb.add_argument("--variant", choices=["A", "B", "C"])
    pb.add_argument("--public", action="store_true", help="Post publicly (default: private/draft where supported).")
    pb.set_defaults(fn=cmd_publish)

    au = sub.add_parser("auth", help="One-time OAuth setup.")
    au.add_argument("platform", choices=["youtube"])
    au.set_defaults(fn=cmd_auth)

    rd = sub.add_parser("render", help="Re-render reel JSON files to Markdown.")
    rd.add_argument("files", nargs="+")
    rd.set_defaults(fn=cmd_render)

    n = sub.add_parser("niches", help="List supported niches.")
    n.set_defaults(fn=lambda _: print("\n".join(NICHES)) or 0)

    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO if a.verbose else logging.WARNING, format="%(message)s")
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
