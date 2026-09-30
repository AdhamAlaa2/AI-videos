"""Prompt text for every pipeline stage.

SYSTEM is identical across calls so it is cached; everything run-specific goes in
the per-stage user prompt.
"""

from __future__ import annotations

from .config import LANGUAGES, SECTIONS, SENSITIVE_NICHES, Thresholds

SYSTEM = """\
You are the creative core of a short-form video studio that makes vertical reels for TikTok, \
Instagram Reels, YouTube Shorts and Facebook Reels. You think like the best short-form \
strategist, a Hollywood story editor and a growth marketer at once.

What the studio optimises for, in order: 3-second hold, completion rate, rewatches, shares, \
saves, follows, comments. Average content is a failure; we would rather ship nothing.

How great reels work:
- The hook lands inside 2 seconds and opens a question the viewer cannot leave unanswered. \
It pairs a spoken line with a visual pattern interrupt; it never starts with a greeting, a \
logo or context.
- Every 5-8 seconds a new open loop is planted before the previous one is closed: a partial \
reveal, a delayed answer, a contradiction, a hidden detail, an unexpected twist.
- Structure: HOOK, CONTEXT, BUILDUP, TWIST, ESCALATION, FINAL_SURPRISE, CTA. The final \
surprise must be the strongest moment, and the last line should make a rewatch feel rewarding \
(a loop back to the first frame, or a detail the viewer missed).
- Write for the ear: short sentences, concrete nouns, numbers, names. One idea per line.
- Psychology you may use: curiosity gap, social proof, FOMO, surprise, suspense, pattern \
interrupts, open loops, reward loops. Use them to make true stories gripping, never to deceive.

Truth rules (non-negotiable):
- Every factual claim must be true and checkable. If you are not confident a fact is true, cut \
it or reframe it ("legend says", "one theory claims"). Never invent quotes, statistics, dates, \
or events and present them as real.
- Crime stories: real cases only with documented facts; respect victims; no glorification; say \
"alleged" where there was no conviction.
- Celebrity news: only publicly reported facts; no rumours presented as fact; nothing \
defamatory or sexualised.
- Conspiracy theories: present them as theories, show what the evidence actually says, and \
land on the documented truth. The twist can be that the real story is stranger than the myth.
- Health and wealth: no medical or financial advice or guaranteed outcomes; no dangerous \
challenges.
- No hate, harassment, or content targeting private individuals.

Visual rules:
- 9:16 vertical, cinematic, ultra-realistic, dramatic lighting, professional composition.
- Image and video prompts are always written in English (generators work best in English), \
regardless of the reel's language, and must be self-contained: repeat the locked character and \
environment descriptions verbatim so every scene stays consistent.
- Do not reproduce real people's likenesses in generated imagery; depict them with archival-\
style silhouettes, crowds, hands, locations and objects instead, unless the prompt describes a \
generic actor.

Return only the requested JSON."""


NICHE_GUARDRAILS = {
    "Crime Stories": "Documented cases only. Say 'alleged' without a conviction. No gore, no glorifying perpetrators.",
    "Celebrity News": "Publicly reported facts only, with the date they were reported. No rumours as fact.",
    "Conspiracy Theories": "Frame as a theory, show the evidence, land on the documented truth.",
    "Health": "Educational, not advice. No miracle cures, no dosages, no dangerous challenges.",
    "Wealth": "No guaranteed returns, no specific investment advice.",
}


def language_line(language: str) -> str:
    name = LANGUAGES[language]
    return (
        f"Write all viewer-facing text (voice-over, captions, titles, hashtags, CTAs) in {name}, "
        f"natively and idiomatically for {name}-speaking audiences - not translated English. "
        "Image and video prompts stay in English."
    )


def ideation(niches: list[str], count: int, language: str, length_sec: int, avoid: list[str]) -> str:
    guard = [f"- {n}: {NICHE_GUARDRAILS[n]}" for n in niches if n in SENSITIVE_NICHES]
    avoid_block = "\n".join(f"- {t}" for t in avoid) or "- (none yet)"
    return f"""\
Generate {count} fresh reel ideas for {length_sec}-second vertical videos.

Niches for this batch (spread ideas across them): {", ".join(niches)}
{language_line(language)}

Each idea needs a premise that creates an itch, a payoff that is genuinely surprising, a \
concrete target audience, and a fact basis. Favour stories with a real twist, a number that \
sounds impossible but is true, or a hidden detail everyone has seen but nobody noticed. Avoid \
stale viral topics everybody has already made.

Score each idea honestly 1-10 on viral_potential, curiosity, emotional_impact, shareability \
and audience_size. A 9 or 10 should be rare.
{"Guardrails:" + chr(10) + chr(10).join(guard) if guard else ""}
Titles already used this cycle (do not repeat or paraphrase):
{avoid_block}"""


def hooks(idea_json: str, language: str, count: int) -> str:
    return f"""\
Idea:
{idea_json}

{language_line(language)}

Write {count} hook variations for this reel. Each must be speakable in under 2 seconds (about 6 \
words), open a curiosity gap tied to this idea's actual payoff, and come with an on-screen \
text and a first-second visual pattern interrupt. Use varied techniques (contradiction, stakes, \
impossible number, direct challenge, mid-action start, hidden detail, countdown...). Generic \
lines like "You won't believe this" only count if the rest of the line makes them specific.

Score each on predicted 3-second hold, pick the best, and pick 2 runners-up that use different \
techniques from the winner so they are worth A/B testing."""


def script(idea_json: str, hook_json: str, language: str, length_sec: int, t: Thresholds, feedback: str) -> str:
    sections = " -> ".join(SECTIONS)
    words = int(length_sec * t.max_words_per_sec)
    fb = f"\n\nPrevious draft failed review. Fix every point:\n{feedback}" if feedback else ""
    return f"""\
Idea:
{idea_json}

Chosen hook:
{hook_json}

{language_line(language)}

Write the full {length_sec}-second script as timed beats in this exact order: {sections}.
Constraints the studio checks automatically:
- Beats are contiguous, start at 0.0 and end at {length_sec}.0.
- HOOK ends by {t.hook_max_sec}s and uses the chosen hook.
- Every beat before FINAL_SURPRISE has a non-empty open_loop, and consecutive open loops start \
no more than {t.open_loop_max_gap_sec:g}s apart. You may split a section across several beats \
to keep that rhythm, but keep the section order.
- Voice-over pace at most {t.max_words_per_sec} words per second per beat (about {words} words total).
- List every factual claim with its support and your confidence. Anything below high \
confidence must be cut from the voice-over or reframed as legend/theory.

Also give: music mood and notes, timed sound effects, and editing instructions (cut rhythm, \
zooms, caption style, colour, where to drop the music, where to insert a freeze-frame or a \
loop point).{fb}"""


def qc(idea_json: str, script_json: str, auto_issues: list[str], min_score: float) -> str:
    auto = "\n".join(f"- {i}" for i in auto_issues) or "- none"
    return f"""\
You are the studio's head of quality. Only the top 1% ships. Review this reel script.

Idea:
{idea_json}

Script:
{script_json}

Automated checks found:
{auto}

Score 1-10 (8 = top 1%): hook_strength, mystery, retention, originality, factual_support, \
emotional_impact. For factual_support, check each claim yourself; a false or unsupportable \
claim scores 1-3 regardless of how good the story is.

Verdict:
- pass: every score >= {min_score:g} and no automated issues.
- revise: fixable - give specific rewrite notes (which beat, what to change, why).
- reject: boring, repetitive, weak premise, or cannot be made factually sound."""


def visuals(idea_json: str, script_json: str, length_sec: int, t: Thresholds) -> str:
    return f"""\
Idea:
{idea_json}

Final script:
{script_json}

Design the visuals for this {length_sec}-second 9:16 reel.
1. A style guide shared by every shot.
2. Character and environment sheets with locked descriptions (reuse verbatim in prompts).
3. Scenes that tile the timeline from 0 to {length_sec}s with no gaps, each at most \
{t.max_scene_sec:g}s (faster cuts in HOOK and TWIST). Scene 1 must be the hook's visual \
interrupt. For each: visual description, camera movement, an image prompt optimised for AI \
image models, a video prompt optimised for AI video models (motion, camera, duration), and a \
negative prompt.
Cinematic, ultra-realistic, dramatic lighting, strong composition, high visual contrast between \
consecutive shots."""


def packaging(idea_json: str, script_json: str, language: str, t: Thresholds) -> str:
    return f"""\
Idea:
{idea_json}

Final script:
{script_json}

{language_line(language)}

Package this reel:
- Exactly {t.titles} titles (curiosity-led, no clickbait the video does not pay off).
- Exactly {t.captions} post captions (first line is a hook, end with a comment prompt).
- Exactly {t.hashtags} hashtags, each starting with #, mixing broad, mid-size and niche tags.
- SEO keywords people actually search for.
- A recommendation for each of TikTok, Instagram Reels, YouTube Shorts and Facebook Reels."""


def ab_test(idea_json: str, script_json: str, hooks_json: str, language: str) -> str:
    return f"""\
Idea:
{idea_json}

Final script:
{script_json}

Hook shortlist:
{hooks_json}

{language_line(language)}

Create A/B/C test variants. A uses the script's current hook. B and C each change the hook, \
title, first 5 seconds and CTA together around a different psychological lever, and state the \
hypothesis and the metric that should move."""
