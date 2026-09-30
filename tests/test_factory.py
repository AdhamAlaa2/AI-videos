import asyncio
from pathlib import Path

import pytest

from reelfactory import validators as V
from reelfactory.config import RunConfig, Thresholds
from reelfactory.llm import GenerationError
from reelfactory.models import (
    ABTest,
    HookSet,
    Idea,
    IdeaBatch,
    IdeaScores,
    Packaging,
    QCReport,
    Reel,
    Script,
    VisualPlan,
)
from reelfactory.pipeline import Factory, rank
from reelfactory.render import to_markdown

EXAMPLE = next(Path(__file__).parent.parent.joinpath("examples").glob("*.json"))
T = Thresholds()


@pytest.fixture
def reel() -> Reel:
    return Reel.model_validate_json(EXAMPLE.read_text(encoding="utf-8"))


def _idea(title: str, score: int) -> Idea:
    s = IdeaScores(viral_potential=score, curiosity=score, emotional_impact=score, shareability=score, audience_size=score)
    return Idea(niche="History", working_title=title, premise="p", payoff="x", target_audience="a", fact_basis="f", scores=s)


# ------------------------------------------------------------------ example


def test_example_reel_passes_every_gate(reel):
    assert V.check_script(reel.script, reel.length_sec, T) == []
    assert V.check_visuals(reel.visuals, reel.length_sec, T) == []
    assert V.check_packaging(reel.packaging, T) == []
    assert V.check_ab(reel.ab_test) == []
    assert len(reel.hook_candidates) == 20


def test_markdown_has_all_15_fields(reel):
    md = to_markdown(reel)
    for n in range(1, 16):
        assert f"{n}. " in md
    assert md.count("**Scene ") == 2 * len(reel.visuals.scenes)  # image + video prompt per scene


# ------------------------------------------------------------------ validators


def test_slow_hook_is_rejected(reel):
    s = reel.script.model_copy(deep=True)
    s.beats[0].end_sec = 4
    s.beats[1].start_sec = 4
    assert any("hook ends" in i for i in V.check_script(s, 45, T))


def test_missing_cliffhanger_is_rejected(reel):
    s = reel.script.model_copy(deep=True)
    for b in s.beats[2:5]:  # BUILDUP, TWIST, ESCALATION: 8s -> 29s with no open loop
        b.open_loop = ""
    issues = V.check_script(s, 45, T)
    assert any("no new open loop" in i for i in issues)


def test_unsupported_claim_is_rejected(reel):
    s = reel.script.model_copy(deep=True)
    s.claims[0].confidence = "medium"
    assert any("not high-confidence" in i for i in V.check_script(s, 45, T))


def test_too_fast_voiceover_is_rejected(reel):
    s = reel.script.model_copy(deep=True)
    s.beats[-1].voiceover = " ".join(["word"] * 40)
    assert any("too fast" in i for i in V.check_script(s, 45, T))


def test_section_order_enforced(reel):
    s = reel.script.model_copy(deep=True)
    s.beats[3].section, s.beats[2].section = s.beats[2].section, s.beats[3].section
    assert any("out of order" in i for i in V.check_script(s, 45, T))


def test_long_scene_and_broken_consistency(reel):
    v = reel.visuals.model_copy(deep=True)
    v.scenes[0].duration_sec = 7
    for sc in v.scenes:
        sc.image_prompt = sc.image_prompt.replace(v.characters[0].locked_description, "Cleopatra")
        sc.video_prompt = sc.video_prompt.replace(v.characters[0].locked_description, "Cleopatra")
    issues = V.check_visuals(v, 45, T)
    assert any("max 5s" in i for i in issues)
    assert any("never reused verbatim" in i for i in issues)


def test_packaging_counts(reel):
    p = reel.packaging.model_copy(deep=True)
    p.hashtags = p.hashtags[:-1] + ["no-hash"]
    p.titles = p.titles[:3]
    issues = V.check_packaging(p, T)
    assert any("15 titles" in i for i in issues)
    assert any("malformed" in i for i in issues)


# ------------------------------------------------------------------ ranking


def test_rank_dedupes_filters_and_sorts():
    ideas = [_idea("A b", 9), _idea("a  B!", 10), _idea("C", 10), _idea("Low", 6), _idea("Bad", 11)]
    ranked = rank(ideas, 8.0)
    assert [i.working_title for i in ranked] == ["C", "A b"]


def test_config_validation():
    with pytest.raises(ValueError):
        RunConfig(language="it")
    with pytest.raises(ValueError):
        RunConfig(niches=["Knitting"])


# ------------------------------------------------------------------ pipeline (fake LLM)


class FakeLLM:
    """Serves stage outputs from the example reel; can be told to fail QC first."""

    def __init__(self, reel: Reel, qc_sequence: list[str] | None = None, broken_script_first: bool = False):
        self.reel = reel
        self.qc_sequence = list(qc_sequence or ["pass"])
        self.broken_script_first = broken_script_first
        self.calls: list[str] = []

    async def generate(self, schema, prompt, *, effort=None):
        self.calls.append(schema.__name__)
        r = self.reel
        if schema is IdeaBatch:
            n = int(prompt.split("Generate ")[1].split()[0])
            ideas = [r.idea.model_copy(update={"working_title": f"{r.idea.working_title} #{i}"}) for i in range(n)]
            return IdeaBatch(ideas=ideas)
        if schema is HookSet:
            return HookSet(hooks=r.hook_candidates, best_index=0, runner_up_indices=[7, 2])
        if schema is Script:
            if self.broken_script_first:
                self.broken_script_first = False
                bad = r.script.model_copy(deep=True)
                bad.beats[0].end_sec = 5
                return bad
            return r.script
        if schema is QCReport:
            verdict = self.qc_sequence.pop(0) if self.qc_sequence else "pass"
            return r.qc.model_copy(update={"verdict": verdict, "revision_notes": "tighten beat 3"})
        return {VisualPlan: r.visuals, Packaging: r.packaging, ABTest: r.ab_test}[schema]


def _cfg(**kw):
    return RunConfig(niches=["History", "Space"], ideas=40, keep=2, **kw)


def test_full_cycle_ships_reels(reel):
    llm = FakeLLM(reel)
    result = asyncio.run(Factory(llm, _cfg()).run_cycle())
    assert len(result.ideas) == 40
    assert len(result.shipped) == 2
    assert llm.calls.count("IdeaBatch") == 2
    out = result.shipped[0]
    assert out.reel_id.startswith("ANC-EN-")
    assert out.virality_score > 8


def test_script_retries_on_validator_failure(reel):
    llm = FakeLLM(reel, broken_script_first=True)
    shipped = asyncio.run(Factory(llm, _cfg()).produce(reel.idea))
    assert shipped.script.beats[0].end_sec == 2
    assert llm.calls.count("Script") == 2


def test_qc_revise_then_pass(reel):
    llm = FakeLLM(reel, qc_sequence=["revise", "pass"])
    asyncio.run(Factory(llm, _cfg()).produce(reel.idea))
    assert llm.calls.count("QCReport") == 2


def test_qc_reject_drops_idea_and_moves_on(reel):
    llm = FakeLLM(reel, qc_sequence=["reject"])
    result = asyncio.run(Factory(llm, _cfg()).run_cycle())
    assert len(result.rejected) == 1
    assert len(result.shipped) == 2  # next ideas in the queue fill the slot


def test_qc_never_passing_raises(reel):
    llm = FakeLLM(reel, qc_sequence=["revise"] * 10)
    with pytest.raises(GenerationError):
        asyncio.run(Factory(llm, _cfg(max_revisions=1)).produce(reel.idea))
