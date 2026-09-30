"""Media production: voice-over, scene visuals, captions and final MP4 assembly."""

from .produce import ProduceResult, apply_variant, produce
from .tts import ElevenLabsTTS, SilentTTS
from .visuals import FalVisuals, PlaceholderVisuals

MODES = ("draft", "stills", "full")


def providers(mode: str):
    """draft: offline storyboard + silent VO (free). stills: AI images + AI voice, Ken Burns motion.
    full: AI images animated by an image-to-video model + AI voice."""
    if mode == "draft":
        return SilentTTS(), PlaceholderVisuals()
    if mode == "stills":
        return ElevenLabsTTS(), FalVisuals(animate=False)
    if mode == "full":
        return ElevenLabsTTS(), FalVisuals(animate=True)
    raise ValueError(f"mode must be one of {MODES}")


__all__ = ["MODES", "ProduceResult", "apply_variant", "produce", "providers"]
