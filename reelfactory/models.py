"""Pydantic models. Each stage's model doubles as the Claude structured-output schema.

Numeric ranges and list lengths are stated in field descriptions (structured
outputs do not enforce them) and checked in code by `validators.py`.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .config import SCORE_WEIGHTS

Section = Literal["HOOK", "CONTEXT", "BUILDUP", "TWIST", "ESCALATION", "FINAL_SURPRISE", "CTA"]


# ---------------------------------------------------------------- discovery


class IdeaScores(BaseModel):
    viral_potential: int = Field(description="1-10")
    curiosity: int = Field(description="1-10")
    emotional_impact: int = Field(description="1-10")
    shareability: int = Field(description="1-10")
    audience_size: int = Field(description="1-10")

    def composite(self) -> float:
        return round(sum(getattr(self, k) * w for k, w in SCORE_WEIGHTS.items()), 2)


class Idea(BaseModel):
    niche: str
    working_title: str
    premise: str = Field(description="One sentence: what the viewer will learn or witness.")
    payoff: str = Field(description="The final surprise that rewards watching to the end.")
    target_audience: str
    fact_basis: str = Field(
        description="The verifiable facts the reel depends on, with where they can be checked. "
        "Write 'story/opinion - no factual claims' if none."
    )
    scores: IdeaScores


class IdeaBatch(BaseModel):
    ideas: list[Idea]


# ---------------------------------------------------------------- hooks


class Hook(BaseModel):
    spoken: str = Field(description="Voice-over line, deliverable in under 2 seconds.")
    on_screen_text: str = Field(description="Max 6 words of burned-in text for frame 1.")
    visual_interrupt: str = Field(description="What the viewer SEES in the first second.")
    technique: str = Field(description="e.g. curiosity gap, contradiction, stakes, pattern interrupt")
    score: int = Field(description="1-10 predicted 3-second hold rate")


class HookSet(BaseModel):
    hooks: list[Hook] = Field(description="Exactly 20 distinct hooks.")
    best_index: int = Field(description="0-based index of the strongest hook.")
    runner_up_indices: list[int] = Field(description="2 other strong, *different-technique* hooks for A/B tests.")


# ---------------------------------------------------------------- script


class Beat(BaseModel):
    section: Section
    start_sec: float
    end_sec: float
    voiceover: str
    on_screen_caption: str = Field(description="Short burned-in caption, max ~8 words.")
    open_loop: str = Field(
        description="The unresolved question this beat plants in the viewer's head. Empty string only for "
        "FINAL_SURPRISE/CTA."
    )
    psychology: list[str] = Field(description="Triggers used: curiosity gap, social proof, FOMO, surprise, ...")


class SoundCue(BaseModel):
    at_sec: float
    effect: str


class Claim(BaseModel):
    statement: str
    support: str = Field(description="Why it is true: source, record, or widely documented reference.")
    confidence: Literal["high", "medium", "low"]


class Script(BaseModel):
    beats: list[Beat]
    music_mood: str
    music_notes: str = Field(description="BPM range, where the drop/stop lands, silence moments.")
    sound_effects: list[SoundCue]
    editing_instructions: list[str]
    cta: str
    claims: list[Claim] = Field(description="Every factual claim the voice-over makes. Empty only for fiction.")


# ---------------------------------------------------------------- QC


class QCScores(BaseModel):
    hook_strength: int
    mystery: int
    retention: int
    originality: int
    factual_support: int
    emotional_impact: int

    def minimum(self) -> int:
        return min(self.model_dump().values())


class QCReport(BaseModel):
    scores: QCScores = Field(description="Each 1-10. Be harsh: 8 means top 1% of short-form content.")
    issues: list[str]
    verdict: Literal["pass", "revise", "reject"]
    revision_notes: str = Field(description="Concrete rewrite instructions if verdict is revise.")


# ---------------------------------------------------------------- visuals


class CharacterSheet(BaseModel):
    name: str
    locked_description: str = Field(
        description="Age, build, face, hair, wardrobe, palette. Pasted verbatim into every prompt featuring them."
    )


class EnvironmentSheet(BaseModel):
    name: str
    locked_description: str


class Scene(BaseModel):
    scene_number: int
    start_sec: float
    duration_sec: float
    section: Section
    visual_description: str
    camera_movement: str
    image_prompt: str = Field(description="English. Subject, setting, lighting, lens, composition, style, 9:16.")
    video_prompt: str = Field(description="English. Motion, camera move, pacing, duration, 9:16.")
    negative_prompt: str


class VisualPlan(BaseModel):
    style_guide: str = Field(description="Shared look: grade, lighting, lens, film stock, aspect 9:16.")
    characters: list[CharacterSheet]
    environments: list[EnvironmentSheet]
    scenes: list[Scene]


# ---------------------------------------------------------------- packaging


class PlatformRec(BaseModel):
    platform: str
    fit: str = Field(description="Why / how to adapt for this platform.")
    best_post_window: str
    on_platform_tweaks: str


class Packaging(BaseModel):
    titles: list[str] = Field(description="Exactly 15.")
    captions: list[str] = Field(description="Exactly 10 post captions.")
    hashtags: list[str] = Field(description="Exactly 25, each starting with #, mix of broad/mid/niche.")
    seo_keywords: list[str]
    platforms: list[PlatformRec]


class Variant(BaseModel):
    label: Literal["A", "B", "C"]
    hook: str
    title: str
    opening: str = Field(description="First 5 seconds of voice-over.")
    cta: str
    hypothesis: str = Field(description="What this variant tests and which metric should move.")


class ABTest(BaseModel):
    variants: list[Variant] = Field(description="Exactly 3: A, B, C.")


# ---------------------------------------------------------------- final reel


class Reel(BaseModel):
    reel_id: str
    niche: str
    language: str
    length_sec: int
    target_audience: str
    virality_score: float
    title: str
    idea: Idea
    hook: Hook
    hook_candidates: list[Hook]
    script: Script
    visuals: VisualPlan
    packaging: Packaging
    ab_test: ABTest
    qc: QCReport
