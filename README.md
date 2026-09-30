# reelfactory — viral short-form video factory

A Claude-powered pipeline for vertical reels (TikTok, Instagram Reels, YouTube Shorts,
Facebook Reels). It writes the reel, renders it to a finished MP4 (AI voice-over, AI visuals,
word-by-word captions, music) and posts it. Every reel passes quality control before it ships.

```
reelfactory run --produce full --publish youtube,tiktok,instagram,facebook
```

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

## From brief to posted video

### Produce: `reelfactory produce <reel.json> --mode draft|stills|full`

| Mode | Voice-over | Visuals | Needs | Rough cost per 45 s reel* |
|---|---|---|---|---|
| `draft` | silent (timed placeholder) | storyboard cards with Ken Burns motion | nothing | free |
| `stills` | ElevenLabs | FLUX 1.1 Pro images with Ken Burns motion | `ELEVENLABS_API_KEY`, `FAL_KEY` | ~$1 |
| `full` | ElevenLabs | FLUX images animated by Kling 2.6 Pro (image-to-video) | same | ~$5-10 |

\*Ballpark figures from public list prices at the time of writing. Check fal.ai and ElevenLabs
pricing before running at volume.

What the renderer does:
1. **Voice-over, one clip per beat.** Each clip is placed at its beat's timestamp, so the voice,
   cuts and captions stay locked to the script. A line that overruns its beat is sped up by up to
   1.25x; anything longer is reported as a warning.
2. **Scene visuals.** Each scene gets a still generated from its image prompt, using a fixed seed
   per reel for a consistent look. In `full` mode the still is the first frame of the AI video
   clip, which keeps characters consistent. If clip generation fails, the scene falls back to the
   animated still.
3. **Captions.** Two layers are burned in: the beat's punch caption in the upper third, and the
   voice-over in 3-word chunks with the spoken word highlighted. The ElevenLabs timestamps drive
   the highlighting. Captions are rendered with libass, so Arabic shapes and reads right to left
   correctly.
4. **Mix.** An optional `--music` bed is ducked under the voice with a sidechain compressor and
   faded out. The final audio is loudness-normalised to −14 LUFS, the standard for social platforms.
5. **Output.** A 1080×1920, 30 fps H.264/AAC `.mp4` of exactly the reel's length, plus
   `manifest.json`. Every intermediate file is cached, so a rerun only pays for what is missing.

`--variant B` renders the B variant's hook and CTA, so you can post A and B as separate videos.

Provider settings:
- `ELEVENLABS_VOICE_ID`, or `ELEVENLABS_VOICE_AR` (and the same for each language) for a native
  voice per language.
- `FAL_IMAGE_MODEL`, `FAL_VIDEO_MODEL` and `FAL_VIDEO_IMAGE_FIELD` switch models. For example,
  Veo or Seedance take `image_url` instead of `start_image_url`.

### Publish: `reelfactory publish <reel.json> --platforms youtube,tiktok,instagram,facebook [--public]`

**Everything is private by default.** YouTube uploads as `private`, TikTok as `SELF_ONLY` and
Facebook as a `DRAFT`. Instagram has no private mode, so it is skipped unless you pass `--public`.
Posts are labelled as AI-generated where the API supports it (YouTube `containsSyntheticMedia`,
TikTok `is_aigc`). Each attempt is logged to `published.json` next to the video.

| Platform | API | Credentials (env vars) | One-time setup |
|---|---|---|---|
| YouTube Shorts | Data API v3, resumable upload | `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN` | Create an OAuth client (Desktop app) in Google Cloud and enable YouTube Data API v3, then run `reelfactory auth youtube` to get the refresh token. The default quota allows about 6 uploads a day; request more from Google if needed. |
| TikTok | Content Posting API, Direct Post | `TIKTOK_ACCESS_TOKEN` (scope `video.publish`) | Register an app at developers.tiktok.com. **Until TikTok audits the app, every post is private**, so public posting needs the audit. |
| Instagram Reels | Graph API, resumable upload | `IG_USER_ID`, `IG_ACCESS_TOKEN`, optional `IG_GRAPH_HOST` | Needs a Business or Creator account and a Meta app with `instagram_content_publish`. |
| Facebook Reels | Graph API `video_reels` | `FB_PAGE_ID`, `FB_PAGE_ACCESS_TOKEN` | Needs a Page token with `pages_manage_posts`. Limit: 30 API posts per 24 h. |

## Usage

```bash
pip install -e ".[dev]"
export ANTHROPIC_API_KEY=...        # or `ant auth login`

# One cycle: 100 ideas across all 30 niches → 3 finished English reels, 45 s
reelfactory run

# Targeted: history + space, English and Arabic, 30 s, ship 5 per language
reelfactory run --niches "History,Space,Ancient Civilizations" --language en,ar --length 30 --keep 5 -v

# Fully autonomous: write, render and post privately for review
reelfactory run --keep 3 --produce full --music bed.mp3 --publish youtube,tiktok,facebook

reelfactory produce output/HIS-EN-1A2B3C.json --mode stills           # render one brief
reelfactory produce output/HIS-EN-1A2B3C.json --mode stills --variant B
reelfactory publish output/HIS-EN-1A2B3C.json --platforms youtube,tiktok --public

reelfactory niches                  # list the 30 niches
reelfactory render output/*.json    # re-render briefs after hand edits
pytest                              # 30 offline tests (no API calls; real ffmpeg render)
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
  cli.py         `reelfactory run | produce | publish | auth | render | niches`
  media/         tts.py (ElevenLabs / silent), visuals.py (fal FLUX + Kling / placeholder),
                 captions.py (ASS word highlighting), produce.py (ffmpeg assembly)
  publish/       youtube.py, tiktok.py, meta.py (Instagram + Facebook)
examples/        a fully worked, fact-checked reel (JSON + Markdown)
tests/           offline tests with a fake LLM
```

## Limits worth knowing

- **Sound effects** are written as a timed cue sheet in `manifest.json`. They are not mixed
  automatically, because licensed SFX libraries vary. Add them in your editor, or extend
  `produce.py` to point at a folder of SFX files.
- **Platform approvals are yours to get.** TikTok keeps posts private until your app is audited.
  Instagram needs a Business or Creator account. YouTube uploads are limited by API quota. The code
  handles each API; the accounts and approvals have to come from you.
- **Real A/B testing** needs your own analytics. The platforms don't split traffic for you, so
  post variants on separate days or accounts and compare retention.
- **Live API runs are untested here.** The publishers and generators are tested against mocked
  HTTP responses that follow each service's docs, not against live accounts. Do a first run with
  one reel, privately, before scaling up.
