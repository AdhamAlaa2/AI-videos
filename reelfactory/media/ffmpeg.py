"""Locate and run ffmpeg. Uses $FFMPEG, then PATH, then the static build bundled by imageio-ffmpeg."""

from __future__ import annotations

import functools
import os
import shutil
import subprocess
import wave
from pathlib import Path


class FFmpegError(RuntimeError):
    pass


@functools.cache
def binary() -> str:
    if exe := os.environ.get("FFMPEG") or shutil.which("ffmpeg"):
        return exe
    try:
        import imageio_ffmpeg
    except ImportError as e:  # pragma: no cover
        raise FFmpegError("ffmpeg not found: install it or `pip install imageio-ffmpeg`") from e
    return imageio_ffmpeg.get_ffmpeg_exe()


def run(*args: str | Path) -> None:
    cmd = [binary(), "-hide_banner", "-loglevel", "error", "-y", *map(str, args)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise FFmpegError(f"ffmpeg failed ({proc.returncode}): {proc.stderr.strip()[-2000:]}\n{' '.join(cmd)}")


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate())


def to_wav(src: Path, dst: Path, rate: int = 44100) -> Path:
    run("-i", src, "-ac", "1", "-ar", str(rate), "-c:a", "pcm_s16le", dst)
    return dst


def silence(dst: Path, seconds: float, rate: int = 44100) -> Path:
    run("-f", "lavfi", "-i", f"anullsrc=r={rate}:cl=mono", "-t", f"{seconds:.3f}", "-c:a", "pcm_s16le", dst)
    return dst
