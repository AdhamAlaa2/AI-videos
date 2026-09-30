"""Burned-in captions as an ASS subtitle file (rendered by ffmpeg/libass, which handles Arabic RTL).

Two layers:
- Punch: the beat's short on-screen caption, large, in the upper third.
- Words: the voice-over in 3-word chunks with the spoken word highlighted (TikTok style).
"""

from __future__ import annotations

from dataclasses import dataclass

from .tts import Word

WHITE, YELLOW, BLACK = "&H00FFFFFF", "&H0000E6FF", "&H00000000"  # ASS colours are &HAABBGGRR


@dataclass
class TimedWord:
    text: str
    start: float  # absolute seconds on the reel timeline
    end: float


@dataclass
class PunchCard:
    text: str
    start: float
    end: float


def _ts(sec: float) -> str:
    sec = max(sec, 0.0)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", " ")


def header(font: str = "DejaVu Sans", w: int = 1080, h: int = 1920) -> str:
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Punch,{font},92,{YELLOW},{WHITE},{BLACK},&H80000000,-1,0,0,0,100,100,0,0,1,7,3,8,70,70,260,1
Style: Words,{font},78,{WHITE},{WHITE},{BLACK},&H80000000,-1,0,0,0,100,100,0,0,1,6,2,2,90,90,560,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def chunk_words(words: list[TimedWord], size: int = 3) -> list[list[TimedWord]]:
    return [words[i : i + size] for i in range(0, len(words), size)]


def build_ass(words: list[TimedWord], cards: list[PunchCard], font: str = "DejaVu Sans") -> str:
    lines = [header(font)]
    for c in cards:
        if c.text.strip():
            lines.append(f"Dialogue: 1,{_ts(c.start)},{_ts(c.end)},Punch,,0,0,0,,{{\\fad(80,80)}}{_esc(c.text)}")
    for group in chunk_words(words):
        for i, w in enumerate(group):
            end = group[i + 1].start if i + 1 < len(group) else w.end
            if end <= w.start:
                end = w.start + 0.05
            text = " ".join(
                f"{{\\c{YELLOW}\\fscx108\\fscy108}}{_esc(x.text)}{{\\r}}" if j == i else _esc(x.text)
                for j, x in enumerate(group)
            )
            lines.append(f"Dialogue: 0,{_ts(w.start)},{_ts(end)},Words,,0,0,0,,{text}")
    return "\n".join(lines) + "\n"


def place(words: list[Word], offset: float, scale: float = 1.0) -> list[TimedWord]:
    """Convert clip-relative word times to reel-absolute times (scale accounts for tempo changes)."""
    return [TimedWord(w.text, offset + w.start * scale, offset + w.end * scale) for w in words]
