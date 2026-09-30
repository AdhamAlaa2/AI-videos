"""Turn a Reel brief into a finished 1080x1920 MP4.

    voice-over (per beat) ─┐
    scene stills / clips ──┼─► normalised scene clips ─► concat ─► + VO/music mix ─► + captions ─► final.mp4
    captions (ASS) ────────┘

Every intermediate is cached in the reel's work directory, so a failed or interrupted run
resumes without paying for finished assets again.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..models import Reel
from . import ffmpeg
from .captions import PunchCard, TimedWord, build_ass, place
from .tts import TTS, VoiceClip, Word
from .visuals import H, W, Visuals

log = logging.getLogger("reelfactory.media")
FPS = 30
MAX_TEMPO = 1.25  # fastest we will speed up a voice line to fit its beat


@dataclass
class ProduceResult:
    video: Path
    captions: Path
    voiceover: Path
    manifest: Path
    warnings: list[str] = field(default_factory=list)


def apply_variant(reel: Reel, label: str) -> Reel:
    """Swap in an A/B/C variant's hook and CTA lines (title is handled at publish time)."""
    variant = next((v for v in reel.ab_test.variants if v.label == label), None)
    if variant is None:
        raise ValueError(f"Reel has no variant {label!r}")
    r = reel.model_copy(deep=True)
    r.script.beats[0].voiceover = variant.hook
    cta = next((b for b in reversed(r.script.beats) if b.section == "CTA"), None)
    if cta:
        cta.voiceover = variant.cta
    r.title = variant.title
    return r


def _part(path: Path) -> Path:
    """Temp name for atomic writes: a crash never leaves a half-written file that looks cached."""
    return path.with_name(f"{path.stem}.part{path.suffix}")


def _seed(reel: Reel) -> int:
    return int(hashlib.sha1(reel.reel_id.encode()).hexdigest()[:8], 16)


def _fit_voice(clip: VoiceClip, window: float, dst: Path, warnings: list[str], label: str) -> tuple[Path, float]:
    """Speed up a line that overruns its beat (up to MAX_TEMPO). Returns (wav, time scale)."""
    if clip.duration <= window or window <= 0:
        return clip.path, 1.0
    tempo = clip.duration / window
    if tempo > MAX_TEMPO:
        warnings.append(f"{label}: voice-over is {clip.duration:.1f}s for a {window:.1f}s beat; it will spill over")
        tempo = MAX_TEMPO
    ffmpeg.run("-i", clip.path, "-filter:a", f"atempo={tempo:.4f}", dst)
    return dst, 1.0 / tempo


def _scene_clip(src: Path, is_video: bool, duration: float, idx: int, dst: Path) -> None:
    frames = max(1, round(duration * FPS))
    base = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1"
    if is_video:
        vf = f"{base},fps={FPS},tpad=stop_mode=clone:stop_duration={duration:.3f},format=yuv420p"
        ffmpeg.run("-i", src, "-an", "-vf", vf, "-t", f"{duration:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", dst)
        return
    # Ken Burns: alternate slow push-in / pull-out so consecutive stills never feel static.
    zoom = "min(1.0+0.0016*on,1.25)" if idx % 2 == 0 else "max(1.25-0.0016*on,1.0)"
    vf = (
        f"{base},scale={W * 2}:{H * 2},zoompan=z='{zoom}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        f":d={frames}:s={W}x{H}:fps={FPS},format=yuv420p"
    )
    ffmpeg.run("-loop", "1", "-i", src, "-vf", vf, "-frames:v", str(frames), "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", dst)


def produce(
    reel: Reel,
    work: Path,
    tts: TTS,
    visuals: Visuals,
    music: Path | None = None,
    variant: str | None = None,
) -> ProduceResult:
    if variant:
        reel = apply_variant(reel, variant)
    work.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    total = float(reel.length_sec)

    # ---- 1. voice-over, one clip per beat, placed at the beat's start
    placed: list[tuple[Path, float]] = []
    words: list[TimedWord] = []
    for i, beat in enumerate(reel.script.beats):
        key = hashlib.sha1(f"{tts.name}|{reel.language}|{beat.voiceover}".encode()).hexdigest()[:10]
        raw = work / f"vo_{i:02d}_{key}.wav"
        meta = raw.with_suffix(".json")
        if raw.exists() and meta.exists():
            m = json.loads(meta.read_text())
            clip = VoiceClip(raw, m["duration"], [Word(**w) for w in m["words"]])
        else:
            clip = tts.synthesize(beat.voiceover, reel.language, _part(raw))
            _part(raw).replace(raw)
            clip.path = raw
            meta.write_text(json.dumps({"duration": clip.duration, "words": [asdict(w) for w in clip.words]}))
        wav, scale = _fit_voice(clip, beat.end_sec - beat.start_sec, work / f"vo_{i:02d}_{key}_fit.wav", warnings, beat.section)
        placed.append((wav, beat.start_sec))
        words += place(clip.words, beat.start_sec, scale)

    vo = work / "voiceover.wav"
    inputs: list[str | Path] = []
    for wav, _ in placed:
        inputs += ["-i", wav]
    delays = ";".join(f"[{i}:a]adelay={int(start * 1000)}:all=1[a{i}]" for i, (_, start) in enumerate(placed))
    mix = "".join(f"[a{i}]" for i in range(len(placed)))
    ffmpeg.run(
        *inputs,
        "-filter_complex",
        f"{delays};{mix}amix=inputs={len(placed)}:normalize=0,apad=whole_dur={total:.3f}[out]",
        "-map", "[out]", "-t", f"{total:.3f}", "-ac", "1", "-ar", "44100", vo,
    )

    # ---- 2. scene visuals -> normalised clips
    style = reel.visuals.style_guide
    clips: list[Path] = []
    for idx, scene in enumerate(sorted(reel.visuals.scenes, key=lambda s: s.start_sec)):
        n = scene.scene_number
        still = work / f"scene_{n:02d}.jpg"
        url_file = work / f"scene_{n:02d}.url"
        if not still.exists():
            visuals.image(scene, style, _seed(reel), _part(still))
            _part(still).replace(still)
            if url := getattr(visuals, "last_image_url", None):
                url_file.write_text(url)
        motion = work / f"scene_{n:02d}_ai.mp4"
        if not motion.exists():
            url = url_file.read_text().strip() if url_file.exists() else None
            try:
                if visuals.video(scene, still, url, _part(motion)):
                    _part(motion).replace(motion)
            except Exception as e:  # animated clip is a bonus; fall back to Ken Burns on the still
                warnings.append(f"scene {n}: video generation failed ({e}); using animated still")
        clip = work / f"clip_{n:02d}.mp4"
        if not clip.exists():
            use_video = motion.exists()
            _scene_clip(motion if use_video else still, use_video, scene.duration_sec, idx, _part(clip))
            _part(clip).replace(clip)
        clips.append(clip)

    concat_list = work / "concat.txt"
    concat_list.write_text("".join(f"file '{c.resolve()}'\n" for c in clips))
    silent_video = work / "video_only.mp4"
    ffmpeg.run("-f", "concat", "-safe", "0", "-i", concat_list, "-c", "copy", silent_video)

    # ---- 3. captions
    ass = work / "captions.ass"
    cards = [PunchCard(b.on_screen_caption, b.start_sec, b.end_sec) for b in reel.script.beats]
    ass.write_text(build_ass(words, cards), encoding="utf-8")

    # ---- 4. final mix: VO (+ ducked music bed), captions burned in, loudness normalised for social
    final = work / (f"{reel.reel_id}{'-' + variant if variant else ''}.mp4")
    ass_arg = str(ass.resolve()).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
    vf = f"subtitles='{ass_arg}'"
    args: list[str | Path] = ["-i", silent_video, "-i", vo]
    if music:
        args += ["-stream_loop", "-1", "-i", music]
        audio = (
            f"[2:a]volume=0.22,afade=t=out:st={max(total - 1.5, 0):.2f}:d=1.5[bed];"
            f"[1:a]asplit=2[vo1][vo2];[bed][vo1]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=300[duck];"
            f"[duck][vo2]amix=inputs=2:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11[a]"
        )
    else:
        audio = "[1:a]loudnorm=I=-14:TP=-1.5:LRA=11[a]"
    ffmpeg.run(
        *args,
        "-filter_complex", f"[0:v]{vf}[v];{audio}",
        "-map", "[v]", "-map", "[a]",
        "-t", f"{total:.3f}",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(FPS),
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart",
        final,
    )

    manifest = work / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "reel_id": reel.reel_id,
                "variant": variant,
                "title": reel.title,
                "video": str(final),
                "tts": tts.name,
                "visuals": visuals.name,
                "music": str(music) if music else None,
                "sound_effect_cues": [c.model_dump() for c in reel.script.sound_effects],
                "warnings": warnings,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    for w in warnings:
        log.warning(w)
    return ProduceResult(final, ass, vo, manifest, warnings)
