"""Deterministic quality gates. Each returns a list of human-readable issues (empty = pass).

These catch what the model cannot be trusted to self-report: timing, cadence, counts.
Issues are fed back into the next revision prompt verbatim.
"""

from __future__ import annotations

import re

from .config import PLATFORMS, SECTIONS, Thresholds
from .models import ABTest, HookSet, Idea, Packaging, Script, VisualPlan

EPS = 0.25


def _words(text: str) -> int:
    return len(re.findall(r"\w+", text, flags=re.UNICODE))


def check_idea(idea: Idea) -> list[str]:
    issues = []
    for k, v in idea.scores.model_dump().items():
        if not 1 <= v <= 10:
            issues.append(f"score {k}={v} outside 1-10")
    return issues


def check_hookset(hs: HookSet, expected: int) -> list[str]:
    issues = []
    if len(hs.hooks) != expected:
        issues.append(f"expected {expected} hooks, got {len(hs.hooks)}")
    if not 0 <= hs.best_index < len(hs.hooks):
        issues.append(f"best_index {hs.best_index} out of range")
    spoken = [h.spoken.strip().lower() for h in hs.hooks]
    if len(set(spoken)) != len(spoken):
        issues.append("duplicate hooks")
    return issues


def check_script(s: Script, length_sec: int, t: Thresholds) -> list[str]:
    issues: list[str] = []
    beats = s.beats
    if not beats:
        return ["script has no beats"]

    # Structure: sections appear in canonical order, each at least once.
    order = [SECTIONS.index(b.section) for b in beats]
    if order != sorted(order):
        issues.append(f"sections out of order: {[b.section for b in beats]}")
    missing = [sec for sec in SECTIONS if sec not in {b.section for b in beats}]
    if missing:
        issues.append(f"missing sections: {missing}")

    # Timeline: contiguous from 0 to length.
    if abs(beats[0].start_sec) > EPS:
        issues.append(f"first beat starts at {beats[0].start_sec}s, must start at 0")
    for prev, cur in zip(beats, beats[1:]):
        if abs(cur.start_sec - prev.end_sec) > EPS:
            issues.append(f"gap/overlap between {prev.end_sec}s and {cur.start_sec}s")
    if abs(beats[-1].end_sec - length_sec) > t.duration_tolerance_sec:
        issues.append(f"ends at {beats[-1].end_sec}s, target {length_sec}s")

    # Hook lands within the first 2 seconds.
    hook = beats[0]
    if hook.section != "HOOK":
        issues.append("first beat is not the HOOK")
    elif hook.end_sec > t.hook_max_sec + EPS:
        issues.append(f"hook ends at {hook.end_sec}s, must land by {t.hook_max_sec}s")

    # Voice-over pace.
    for b in beats:
        dur = max(b.end_sec - b.start_sec, 0.1)
        wps = _words(b.voiceover) / dur
        if wps > t.max_words_per_sec + 0.2:
            issues.append(f"{b.section} @{b.start_sec}s too fast: {wps:.1f} words/s")

    # Cliffhanger cadence: an open loop at least every N seconds until the final surprise.
    payoff_at = next((b.start_sec for b in beats if b.section == "FINAL_SURPRISE"), beats[-1].end_sec)
    loops = [b.start_sec for b in beats if b.open_loop.strip() and b.start_sec < payoff_at]
    checkpoints = [0.0, *loops, payoff_at]
    if not loops:
        issues.append("no open loops before the final surprise")
    for a, b in zip(checkpoints, checkpoints[1:]):
        if b - a > t.open_loop_max_gap_sec + EPS:
            issues.append(f"no new open loop between {a:g}s and {b:g}s (max gap {t.open_loop_max_gap_sec:g}s)")
    for b in beats:
        if b.start_sec < payoff_at and b.section != "CTA" and not b.open_loop.strip():
            issues.append(f"{b.section} @{b.start_sec}s resolves without opening a new loop")

    # Facts.
    for c in s.claims:
        if c.confidence != "high":
            issues.append(f"claim not high-confidence (cut or reframe): {c.statement!r}")
    if not s.cta.strip():
        issues.append("missing CTA")
    return issues


def check_visuals(v: VisualPlan, length_sec: int, t: Thresholds) -> list[str]:
    issues: list[str] = []
    scenes = sorted(v.scenes, key=lambda s: s.start_sec)
    if not scenes:
        return ["no scenes"]
    if [s.scene_number for s in scenes] != list(range(1, len(scenes) + 1)):
        issues.append("scene numbers must run 1..N in timeline order")
    if abs(scenes[0].start_sec) > EPS:
        issues.append("first scene must start at 0")
    for prev, cur in zip(scenes, scenes[1:]):
        if abs(cur.start_sec - (prev.start_sec + prev.duration_sec)) > EPS:
            issues.append(f"scene {prev.scene_number}->{cur.scene_number} gap/overlap")
    end = scenes[-1].start_sec + scenes[-1].duration_sec
    if abs(end - length_sec) > t.duration_tolerance_sec:
        issues.append(f"scenes end at {end:g}s, target {length_sec}s")
    for s in scenes:
        if s.duration_sec > t.max_scene_sec + EPS:
            issues.append(f"scene {s.scene_number} is {s.duration_sec:g}s (max {t.max_scene_sec:g}s)")
        if not s.image_prompt.strip() or not s.video_prompt.strip():
            issues.append(f"scene {s.scene_number} missing image/video prompt")
    # Consistency: every locked character description must be reused verbatim somewhere.
    prompts = " ".join(s.image_prompt + " " + s.video_prompt for s in scenes)
    for c in v.characters:
        if c.locked_description not in prompts:
            issues.append(f"character {c.name!r} locked description never reused verbatim")
    return issues


def check_packaging(p: Packaging, t: Thresholds) -> list[str]:
    issues = []
    for name, items, want in (("titles", p.titles, t.titles), ("captions", p.captions, t.captions)):
        if len(items) != want:
            issues.append(f"expected {want} {name}, got {len(items)}")
    if len(p.hashtags) != t.hashtags:
        issues.append(f"expected {t.hashtags} hashtags, got {len(p.hashtags)}")
    bad = [h for h in p.hashtags if not re.fullmatch(r"#\w+", h, flags=re.UNICODE)]
    if bad:
        issues.append(f"malformed hashtags: {bad}")
    if len({h.lower() for h in p.hashtags}) != len(p.hashtags):
        issues.append("duplicate hashtags")
    covered = {r.platform for r in p.platforms}
    missing = [pl for pl in PLATFORMS if pl not in covered]
    if missing:
        issues.append(f"missing platform recommendations: {missing}")
    return issues


def check_ab(ab: ABTest) -> list[str]:
    issues = []
    if sorted(v.label for v in ab.variants) != ["A", "B", "C"]:
        issues.append("variants must be exactly A, B, C")
    hooks = {v.hook.strip().lower() for v in ab.variants}
    if len(hooks) != len(ab.variants):
        issues.append("variants must use different hooks")
    return issues
