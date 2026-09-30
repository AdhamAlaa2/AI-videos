"""Voice-over synthesis, one clip per beat so audio, captions and cuts stay locked to the script timeline."""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx

from . import ffmpeg


@dataclass
class Word:
    text: str
    start: float  # seconds, relative to the clip
    end: float


@dataclass
class VoiceClip:
    path: Path  # mono 44.1 kHz wav
    duration: float
    words: list[Word]


class TTS(Protocol):
    name: str

    def synthesize(self, text: str, language: str, dst: Path) -> VoiceClip: ...


def words_from_alignment(chars: list[str], starts: list[float], ends: list[float]) -> list[Word]:
    """Group ElevenLabs character-level alignment into words."""
    words: list[Word] = []
    buf, w_start, w_end = "", 0.0, 0.0
    for ch, s, e in zip(chars, starts, ends):
        if ch.isspace():
            if buf:
                words.append(Word(buf, w_start, w_end))
                buf = ""
            continue
        if not buf:
            w_start = s
        buf += ch
        w_end = e
    if buf:
        words.append(Word(buf, w_start, w_end))
    return words


def even_words(text: str, duration: float) -> list[Word]:
    toks = text.split()
    if not toks:
        return []
    step = duration / len(toks)
    return [Word(t, i * step, (i + 1) * step) for i, t in enumerate(toks)]


class SilentTTS:
    """Offline draft voice: silence sized to a natural reading pace, with evenly spaced word timings.

    Lets the whole pipeline (captions, timing, assembly) run with no API keys.
    """

    name = "silent"

    def __init__(self, words_per_sec: float = 2.8) -> None:
        self.wps = words_per_sec

    def synthesize(self, text: str, language: str, dst: Path) -> VoiceClip:
        duration = max(0.6, len(text.split()) / self.wps)
        ffmpeg.silence(dst, duration)
        return VoiceClip(dst, duration, even_words(text, duration))


class ElevenLabsTTS:
    """ElevenLabs text-to-speech with character timestamps (drives word-by-word captions).

    eleven_multilingual_v2 covers English, Arabic, Spanish, French and German with one voice.
    Voices per language can be set with ELEVENLABS_VOICE_<LANG> (e.g. ELEVENLABS_VOICE_AR).
    """

    name = "elevenlabs"
    URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice}/with-timestamps"

    def __init__(
        self,
        api_key: str | None = None,
        voice_id: str | None = None,
        model_id: str = "eleven_multilingual_v2",
        http: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("ELEVENLABS_API_KEY", "")
        if not self.api_key:
            raise ValueError("ELEVENLABS_API_KEY is not set")
        self.voice_id = voice_id or os.environ.get("ELEVENLABS_VOICE_ID", "")
        self.model_id = model_id
        self.http = http or httpx.Client(timeout=120)

    def _voice(self, language: str) -> str:
        voice = os.environ.get(f"ELEVENLABS_VOICE_{language.upper()}") or self.voice_id
        if not voice:
            raise ValueError("Set ELEVENLABS_VOICE_ID (or ELEVENLABS_VOICE_<LANG>) to a voice id from your ElevenLabs library")
        return voice

    def synthesize(self, text: str, language: str, dst: Path) -> VoiceClip:
        r = self.http.post(
            self.URL.format(voice=self._voice(language)),
            headers={"xi-api-key": self.api_key, "Content-Type": "application/json"},
            json={
                "text": text,
                "model_id": self.model_id,
                "output_format": "mp3_44100_128",
                "voice_settings": {"stability": 0.4, "similarity_boost": 0.8, "style": 0.35, "use_speaker_boost": True},
            },
        )
        r.raise_for_status()
        data = r.json()
        mp3 = dst.with_suffix(".mp3")
        mp3.write_bytes(base64.b64decode(data["audio_base64"]))
        ffmpeg.to_wav(mp3, dst)
        al = data.get("alignment") or {}
        words = words_from_alignment(
            al.get("characters", []), al.get("character_start_times_seconds", []), al.get("character_end_times_seconds", [])
        )
        duration = ffmpeg.wav_duration(dst)
        return VoiceClip(dst, duration, words or even_words(text, duration))
