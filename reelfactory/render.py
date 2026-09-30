"""Render a Reel as a production-ready Markdown brief (the 15 required output fields, in order)."""

from __future__ import annotations

from .config import LANGUAGES
from .models import Reel


def _t(sec: float) -> str:
    return f"{int(sec // 60)}:{sec % 60:04.1f}"


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def to_markdown(r: Reel) -> str:
    s, v, p = r.script, r.visuals, r.packaging
    out: list[str] = []
    w = out.append

    w(f"# {r.reel_id} - {r.title}\n")
    w("| Field | Value |\n|---|---|")
    w(f"| 1. Reel ID | `{r.reel_id}` |")
    w(f"| 2. Niche | {r.niche} |")
    w(f"| 3. Target audience | {_cell(r.target_audience)} |")
    w(f"| 4. Virality score | **{r.virality_score}/10** (idea {r.idea.scores.composite()}, QC min {r.qc.scores.minimum()}) |")
    w(f"| 5. Title | {_cell(r.title)} |")
    w(f"| 6. Hook | \"{_cell(r.hook.spoken)}\" - on screen: **{_cell(r.hook.on_screen_text)}** |")
    w(f"| Language / length | {LANGUAGES.get(r.language, r.language)} / {r.length_sec}s |")
    w("")
    w(f"**Premise:** {r.idea.premise}\n\n**Payoff:** {r.idea.payoff}\n")

    w("## 7. Full script\n")
    w("| Time | Section | Voice-over | On-screen caption | Open loop |\n|---|---|---|---|---|")
    for b in s.beats:
        w(
            f"| {_t(b.start_sec)}-{_t(b.end_sec)} | {b.section} | {_cell(b.voiceover)} | "
            f"{_cell(b.on_screen_caption)} | {_cell(b.open_loop) or '-'} |"
        )
    w(f"\n**Music:** {s.music_mood}. {s.music_notes}\n")
    w("**Sound effects:**")
    for c in s.sound_effects:
        w(f"- `{_t(c.at_sec)}` {c.effect}")
    w("\n**Editing instructions:**")
    for e in s.editing_instructions:
        w(f"- {e}")

    w("\n## 8. Scene-by-scene breakdown\n")
    w(f"**Style guide:** {v.style_guide}\n")
    if v.characters:
        w("**Characters (locked):**")
        for c in v.characters:
            w(f"- **{c.name}:** {c.locked_description}")
    if v.environments:
        w("\n**Environments (locked):**")
        for e in v.environments:
            w(f"- **{e.name}:** {e.locked_description}")
    w("\n| # | Time | Section | Visual | Camera |\n|---|---|---|---|---|")
    for sc in v.scenes:
        w(
            f"| {sc.scene_number} | {_t(sc.start_sec)} +{sc.duration_sec:g}s | {sc.section} | "
            f"{_cell(sc.visual_description)} | {_cell(sc.camera_movement)} |"
        )

    w("\n## 9. AI image prompts\n")
    for sc in v.scenes:
        w(f"**Scene {sc.scene_number}**\n```\n{sc.image_prompt}\n```\nNegative: `{sc.negative_prompt}`\n")
    w("## 10. AI video prompts\n")
    for sc in v.scenes:
        w(f"**Scene {sc.scene_number}** ({sc.duration_sec:g}s)\n```\n{sc.video_prompt}\n```\n")

    w("## 11. Voice-over (read-through)\n")
    w("> " + " ".join(b.voiceover for b in s.beats) + "\n")

    w("## 12. Captions\n")
    for i, c in enumerate(p.captions, 1):
        w(f"{i}. {c}")
    w("\n**All titles:**")
    for i, t in enumerate(p.titles, 1):
        w(f"{i}. {t}")

    w("\n## 13. Hashtags\n")
    w(" ".join(p.hashtags))
    w(f"\n**SEO keywords:** {', '.join(p.seo_keywords)}\n")

    w("## 14. CTA\n")
    w(s.cta + "\n")

    w("## 15. Platform recommendations\n")
    w("| Platform | Fit | Post window | Tweaks |\n|---|---|---|---|")
    for pr in p.platforms:
        w(f"| {pr.platform} | {_cell(pr.fit)} | {_cell(pr.best_post_window)} | {_cell(pr.on_platform_tweaks)} |")

    w("\n## A/B/C test\n")
    w("| Variant | Hook | Title | Opening (0-5s) | CTA | Hypothesis |\n|---|---|---|---|---|---|")
    for va in sorted(r.ab_test.variants, key=lambda x: x.label):
        w(
            f"| {va.label} | {_cell(va.hook)} | {_cell(va.title)} | {_cell(va.opening)} | "
            f"{_cell(va.cta)} | {_cell(va.hypothesis)} |"
        )

    w("\n## Fact check\n")
    if s.claims:
        w("| Claim | Support | Confidence |\n|---|---|---|")
        for c in s.claims:
            w(f"| {_cell(c.statement)} | {_cell(c.support)} | {c.confidence} |")
    else:
        w("No factual claims.")

    w("\n## Quality control\n")
    sc_ = r.qc.scores.model_dump()
    w(" | ".join(f"{k.replace('_', ' ')}: **{val}**" for k, val in sc_.items()))
    w(f"\nVerdict: **{r.qc.verdict.upper()}**")
    for i in r.qc.issues:
        w(f"- {i}")

    w("\n<details><summary>All 20 hook candidates</summary>\n")
    w("| # | Hook | Technique | Score |\n|---|---|---|---|")
    for i, h in enumerate(r.hook_candidates):
        mark = " (chosen)" if h == r.hook else ""
        w(f"| {i + 1} | {_cell(h.spoken)}{mark} | {_cell(h.technique)} | {h.score} |")
    w("\n</details>\n")
    return "\n".join(out)
