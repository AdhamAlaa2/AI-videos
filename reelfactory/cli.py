"""Command line entry point.

    reelfactory run --niches History,Space --language en --length 45 --ideas 100 --keep 3
    reelfactory render examples/HIS-EN-CLEO01.json
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


def cmd_run(a: argparse.Namespace) -> int:
    from .llm import ClaudeLLM
    from .pipeline import Factory

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
            print(f"  {reel.virality_score:>5}  {_write(reel, out)}")
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
    r.set_defaults(fn=cmd_run)

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
