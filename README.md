# reelfactory — viral short-form video factory

A Claude-powered pipeline that turns one command into finished production briefs for vertical
reels (TikTok, Instagram Reels, YouTube Shorts, Facebook Reels). A brief has a timed script,
scene-by-scene AI image and video prompts, packaging and A/B/C variants. Every reel passes
quality control before it ships.

**See a finished reel:** [`examples/ANC-EN-5F6766.md`](examples/ANC-EN-5F6766.md). The example
is *"Cleopatra is closer to iPhones than pyramids"*, a 45-second reel. It has 8 timed beats,
14 scenes with image and video prompts, 20 hook candidates, 15 titles, 10 captions and
25 hashtags. It also includes A/B/C variants, a fact-check table with sources and a QC report.

## The production cycle

```
discover ──► rank ──► hooks ──► script ◄──► QC ──► visuals ┐
100 ideas    top 1%   20 → 1    7-part beats  critic  packaging ├─► Reel (JSON + Markdown)
(5 parallel  (score,  + 2 A/B   + validators  pass/   A/B/C    ┘
 batches)    dedupe)  runners-up               revise/reject
```

| Stage | What happens | Gate |
|---|---|---|
| **Discover** | 100 ideas across the chosen niches, in 5 parallel batches of 20. Each idea is scored 1-10 on viral potential, curiosity, emotional impact, shareability and audience size. Past titles are fed back so cycles don't repeat themselves. | Dedupe, weighted composite of at least 8.0 |
| **Hooks** | 20 hook variations (spoken line, frame-1 text, visual interrupt, technique). The best one is picked, plus 2 runners-up that use different techniques for A/B tests. | Exactly 20, no duplicates |
| **Script** | HOOK → CONTEXT → BUILDUP → TWIST → ESCALATION → FINAL_SURPRISE → CTA as timed beats. Each beat has a voice-over, a caption, an **open loop** and psychology triggers. The script also has music, timed SFX, editing instructions and a list of every factual claim. | See validators below |
| **QC** | A harsh critic scores hook strength, mystery, retention, originality, factual support and emotional impact. It returns **pass**, **revise** (with rewrite notes that feed the next draft) or **reject**. | Every score at least 8, up to 2 revisions |
| **Visuals** | A style guide, *locked* character and environment sheets, and scenes that tile the timeline. Each scene has a camera move, an image prompt, a video prompt and a negative prompt. | Covers 0 to N seconds, scenes of 5 s or less, locked descriptions reused word for word |
| **Packaging** | 15 titles, 10 captions, 25 hashtags, SEO keywords, and advice for each platform. | Exact counts, valid unique hashtags, all 4 platforms |
| **A/B/C** | Variants that change the hook, title, first 5 seconds and CTA. Each states a hypothesis and the metric it should move. | 3 variants with distinct hooks |

### Deterministic quality gates (`reelfactory/validators.py`)

The model is never trusted to grade its own timing. The code checks:

- **The hook lands within 2 s.**
- **A cliffhanger every 8 s or less:** a new open loop is planted at least every 8 seconds until the final surprise.
- **All 7 story sections**, in order, on a timeline with no gaps that hits the target length (15/30/45/60 s).
- **Speaking pace of 3.3 words per second or less** in every beat, so the voice-over fits.
- **Only high-confidence claims:** a medium- or low-confidence claim fails the script, which must cut it or reframe it as legend or theory.

A failed check is fed back as rewrite instructions (up to 3 attempts per stage). Only reels
that pass every gate *and* the QC critic ship. This is the "only keep the top 1%" rule turned
into code.

### Truth and safety rules (built into the system prompt)

Viral does not mean made up. Crime reels use documented cases and say "alleged" when there was
no conviction. Celebrity reels use only reported facts. Conspiracy reels present the theory,
then land on the evidence. Health and wealth reels give no advice and promise no outcomes.
Generated imagery avoids real people's likenesses. These rules keep reels shareable without
risking takedowns or defamation.

## Usage

```bash
pip install -e ".[dev]"
export ANTHROPIC_API_KEY=...        # or `ant auth login`

# One cycle: 100 ideas across all 30 niches → 3 finished English reels, 45 s
reelfactory run

# Targeted: history + space, English and Arabic, 30 s, ship 5 per language
reelfactory run --niches "History,Space,Ancient Civilizations" --language en,ar --length 30 --keep 5 -v

reelfactory niches                  # list the 30 niches
reelfactory render output/*.json    # re-render briefs after hand edits
pytest                              # 16 offline tests (fake LLM, no API calls)
```

Output goes to `output/<REEL_ID>.json` (machine-readable, ready for editing and TTS tools) and
`output/<REEL_ID>.md` (a brief for a human editor). The Markdown lists the 15 required fields in
order: Reel ID, niche, target audience, virality score, title, hook, full script, scene
breakdown, image prompts, video prompts, voice-over, captions, hashtags, CTA and platform
recommendations. It then adds the A/B/C table, the fact check, QC scores and all 20 hooks.

**Languages:** `en`, `ar`, `es`, `fr`, `de`. Viewer-facing text is written natively in the
target language, not translated. Image and video prompts stay in English because generators
work best in English.

## Model and API notes

- Uses `claude-opus-5-5` with adaptive thinking. Effort is `high` for the creative and critic
  stages and `medium` for bulk ideation and packaging. Change it with `--model` or `--effort`.
- Each stage makes one streamed request that returns **structured output**: the Pydantic models
  in `reelfactory/models.py` are the JSON schemas, so there is no brittle parsing.
- Server-side refusal fallbacks are on (`fallbacks: "default"`), so a safety-classifier false
  positive in the crime or conspiracy niches reroutes the request instead of failing the cycle.
  Pass `ClaudeLLM(use_fallbacks=False)` to turn this off.
- Rough cost for one default cycle (100 ideas → 3 reels) is about 20-30 requests. Keep
  `--keep` small while you tune.

## Layout

```
reelfactory/
  config.py      niches, languages, lengths, score weights, thresholds
  models.py      Pydantic schemas (also the structured-output schemas)
  prompts.py     system prompt + one prompt builder per stage
  llm.py         Claude wrapper (streaming, structured output, fallbacks, refusal handling)
  validators.py  deterministic quality gates
  pipeline.py    Factory: discover → rank → produce → run_cycle
  render.py      Reel → Markdown brief
  cli.py         `reelfactory run | render | niches`
examples/        a fully worked, fact-checked reel (JSON + Markdown)
tests/           offline tests with a fake LLM
```

## What it does not do (yet)

It writes production-ready briefs and prompts. It does not call image, video or TTS
generators, and it does not post to platforms. Those tools change quickly and each needs its
own account. The JSON output is designed to be piped into them (one image and one video prompt
per scene, voice-over split by beat with timestamps). Real "viral" optimisation also needs your
own retention and share data from each platform, fed back into the idea scoring.
