"""Static configuration: niches, languages, story structure and quality thresholds."""

from __future__ import annotations

from dataclasses import dataclass, field

NICHES: tuple[str, ...] = (
    "Sports",
    "Football",
    "NBA",
    "UFC",
    "Fashion",
    "Luxury",
    "Entrepreneurship",
    "Motivation",
    "Wealth",
    "AI",
    "Technology",
    "History",
    "Mystery",
    "Crime Stories",
    "Ancient Civilizations",
    "Space",
    "Science",
    "Psychology",
    "Dating",
    "Productivity",
    "Self Improvement",
    "Travel",
    "Cars",
    "Celebrity News",
    "Entertainment",
    "Gaming",
    "Health",
    "Business",
    "Conspiracy Theories",
    "Fascinating Facts",
)

# Niches where every factual claim must survive the fact-check gate, and where
# extra framing rules apply (see prompts.NICHE_GUARDRAILS).
SENSITIVE_NICHES: frozenset[str] = frozenset(
    {"Crime Stories", "Celebrity News", "Conspiracy Theories", "Health", "Wealth"}
)

LANGUAGES: dict[str, str] = {
    "en": "English",
    "ar": "Arabic",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
}

LENGTHS: tuple[int, ...] = (15, 30, 45, 60)

# Story structure, in order. Every script must contain each section exactly once.
SECTIONS: tuple[str, ...] = (
    "HOOK",
    "CONTEXT",
    "BUILDUP",
    "TWIST",
    "ESCALATION",
    "FINAL_SURPRISE",
    "CTA",
)

PLATFORMS: tuple[str, ...] = (
    "TikTok",
    "Instagram Reels",
    "YouTube Shorts",
    "Facebook Reels",
)

# Idea score weights (sum to 1.0). Viral potential and curiosity dominate because
# they drive the first 3 seconds, which decide whether the rest is ever seen.
SCORE_WEIGHTS: dict[str, float] = {
    "viral_potential": 0.30,
    "curiosity": 0.25,
    "emotional_impact": 0.20,
    "shareability": 0.15,
    "audience_size": 0.10,
}


@dataclass(frozen=True)
class Thresholds:
    hook_max_sec: float = 2.0  # hook must land inside the first 2 seconds
    open_loop_max_gap_sec: float = 8.0  # a new unresolved question at least every 8s
    max_words_per_sec: float = 3.3  # fast-but-intelligible short-form delivery
    max_scene_sec: float = 5.0  # visual cut at least every 5s
    duration_tolerance_sec: float = 1.0
    min_idea_score: float = 8.0  # composite idea score to enter production
    min_qc_score: float = 8.0  # every QC dimension must reach this to ship
    hook_candidates: int = 20
    titles: int = 15
    captions: int = 10
    hashtags: int = 25


@dataclass
class RunConfig:
    niches: list[str] = field(default_factory=lambda: list(NICHES))
    language: str = "en"
    length_sec: int = 45
    ideas: int = 100
    keep: int = 3  # finished reels to ship per cycle
    model: str = "claude-opus-5-5"
    effort: str = "high"
    max_revisions: int = 2
    thresholds: Thresholds = field(default_factory=Thresholds)

    def __post_init__(self) -> None:
        unknown = [n for n in self.niches if n not in NICHES]
        if unknown:
            raise ValueError(f"Unknown niche(s): {unknown}. Choose from: {', '.join(NICHES)}")
        if self.language not in LANGUAGES:
            raise ValueError(f"Unknown language {self.language!r}. Choose from: {', '.join(LANGUAGES)}")
        if self.length_sec not in LENGTHS:
            raise ValueError(f"Length must be one of {LENGTHS}")
        if self.keep < 1 or self.ideas < self.keep:
            raise ValueError("Need ideas >= keep >= 1")
