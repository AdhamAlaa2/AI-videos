"""The production cycle: discover -> rank -> hook -> script <-> QC -> visuals/packaging/A-B -> ship."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from dataclasses import dataclass, field
from typing import Callable, TypeVar

from pydantic import BaseModel

from . import prompts, validators
from .config import RunConfig
from .llm import LLM, GenerationError
from .models import ABTest, Hook, HookSet, Idea, IdeaBatch, Packaging, QCReport, Reel, Script, VisualPlan

log = logging.getLogger("reelfactory")
T = TypeVar("T", bound=BaseModel)

IDEA_BATCH = 20  # ideas per request; batches run concurrently


@dataclass
class CycleResult:
    ideas: list[Idea]
    shipped: list[Reel] = field(default_factory=list)
    rejected: list[tuple[str, str]] = field(default_factory=list)  # (working_title, reason)


def _dump(m: BaseModel) -> str:
    return m.model_dump_json(indent=1)


def _norm(title: str) -> str:
    return re.sub(r"[^\w]+", " ", title.lower(), flags=re.UNICODE).strip()


def reel_id(idea: Idea, language: str) -> str:
    prefix = re.sub(r"[^A-Z]", "", idea.niche.upper())[:3] or "GEN"
    digest = hashlib.sha1(f"{idea.working_title}|{language}".encode()).hexdigest()[:6].upper()
    return f"{prefix}-{language.upper()}-{digest}"


def rank(ideas: list[Idea], min_score: float) -> list[Idea]:
    """Dedupe, drop malformed, sort by composite score; keep only those above the bar."""
    seen: set[str] = set()
    unique = []
    for i in ideas:
        key = _norm(i.working_title)
        if key in seen or validators.check_idea(i):
            continue
        seen.add(key)
        unique.append(i)
    unique.sort(key=lambda i: i.scores.composite(), reverse=True)
    return [i for i in unique if i.scores.composite() >= min_score]


class Factory:
    def __init__(self, llm: LLM, cfg: RunConfig, avoid_titles: list[str] | None = None) -> None:
        self.llm = llm
        self.cfg = cfg
        self.t = cfg.thresholds
        self.avoid_titles = avoid_titles or []  # past reels, so cycles don't repeat themselves

    async def _gen(
        self,
        schema: type[T],
        build_prompt: Callable[[str], str],
        check: Callable[[T], list[str]],
        attempts: int = 3,
        effort: str | None = None,
    ) -> T:
        """Generate, run deterministic checks, retry with the issues as feedback."""
        feedback = ""
        issues: list[str] = []
        for _ in range(attempts):
            out = await self.llm.generate(schema, build_prompt(feedback), effort=effort)
            issues = check(out)
            if not issues:
                return out
            feedback = "\n".join(f"- {i}" for i in issues)
            log.info("%s failed checks, retrying: %s", schema.__name__, issues)
        raise GenerationError(f"{schema.__name__} still failing after {attempts} attempts: {issues}")

    # ------------------------------------------------------------ discovery

    async def discover(self) -> list[Idea]:
        n_batches = -(-self.cfg.ideas // IDEA_BATCH)
        niches = self.cfg.niches
        # Rotate niches so each batch covers a different slice and the cycle covers all of them.
        per = max(1, -(-len(niches) // n_batches))
        slices = [[niches[(b * per + k) % len(niches)] for k in range(per)] for b in range(n_batches)]

        async def batch(i: int) -> list[Idea]:
            count = min(IDEA_BATCH, self.cfg.ideas - i * IDEA_BATCH)
            prompt = prompts.ideation(sorted(set(slices[i])), count, self.cfg.language, self.cfg.length_sec, self.avoid_titles)
            try:
                return (await self.llm.generate(IdeaBatch, prompt, effort="medium")).ideas
            except GenerationError as e:
                log.warning("idea batch %d failed: %s", i, e)
                return []

        results = await asyncio.gather(*(batch(i) for i in range(n_batches)))
        return [idea for r in results for idea in r]

    # ------------------------------------------------------------ production

    async def produce(self, idea: Idea) -> Reel:
        cfg, t = self.cfg, self.t
        idea_json = _dump(idea)

        hookset = await self._gen(
            HookSet,
            lambda fb: prompts.hooks(idea_json, cfg.language, t.hook_candidates)
            + (f"\n\nFix:\n{fb}" if fb else ""),
            lambda hs: validators.check_hookset(hs, t.hook_candidates),
        )
        hook = hookset.hooks[hookset.best_index]
        hook_json = _dump(hook)

        # Script <-> QC loop: deterministic checks first, then the critic.
        feedback = ""
        script: Script | None = None
        qc: QCReport | None = None
        for _ in range(cfg.max_revisions + 1):
            script = await self._gen(
                Script,
                lambda fb, prior=feedback: prompts.script(
                    idea_json, hook_json, cfg.language, cfg.length_sec, t, "\n".join(x for x in (prior, fb) if x)
                ),
                lambda s: validators.check_script(s, cfg.length_sec, t),
            )
            qc = await self.llm.generate(
                QCReport, prompts.qc(idea_json, _dump(script), [], t.min_qc_score), effort="high"
            )
            if qc.verdict == "pass" and qc.scores.minimum() >= t.min_qc_score:
                break
            if qc.verdict == "reject":
                raise GenerationError(f"QC rejected: {'; '.join(qc.issues) or qc.revision_notes}")
            feedback = qc.revision_notes + "\n" + "\n".join(f"- {i}" for i in qc.issues)
        else:
            raise GenerationError(f"QC never passed after {cfg.max_revisions} revisions: {qc.issues if qc else ''}")

        script_json = _dump(script)
        runners = [hookset.hooks[i] for i in hookset.runner_up_indices if 0 <= i < len(hookset.hooks)]
        shortlist_json = "[" + ",".join(h.model_dump_json() for h in [hook, *runners]) + "]"

        visuals, packaging, ab = await asyncio.gather(
            self._gen(
                VisualPlan,
                lambda fb: prompts.visuals(idea_json, script_json, cfg.length_sec, t)
                + (f"\n\nFix:\n{fb}" if fb else ""),
                lambda v: validators.check_visuals(v, cfg.length_sec, t),
            ),
            self._gen(
                Packaging,
                lambda fb: prompts.packaging(idea_json, script_json, cfg.language, t)
                + (f"\n\nFix:\n{fb}" if fb else ""),
                lambda p: validators.check_packaging(p, t),
                effort="medium",
            ),
            self._gen(
                ABTest,
                lambda fb: prompts.ab_test(idea_json, script_json, shortlist_json, cfg.language)
                + (f"\n\nFix:\n{fb}" if fb else ""),
                validators.check_ab,
                effort="medium",
            ),
        )

        virality = round((idea.scores.composite() + sum(qc.scores.model_dump().values()) / 6) / 2, 2)
        return Reel(
            reel_id=reel_id(idea, cfg.language),
            niche=idea.niche,
            language=cfg.language,
            length_sec=cfg.length_sec,
            target_audience=idea.target_audience,
            virality_score=virality,
            title=packaging.titles[0],
            idea=idea,
            hook=hook,
            hook_candidates=hookset.hooks,
            script=script,
            visuals=visuals,
            packaging=packaging,
            ab_test=ab,
            qc=qc,
        )

    # ------------------------------------------------------------ cycle

    async def run_cycle(self) -> CycleResult:
        ideas = await self.discover()
        ranked = rank(ideas, self.t.min_idea_score)
        log.info("%d ideas generated, %d above the bar", len(ideas), len(ranked))
        result = CycleResult(ideas=ideas)

        # Produce in waves until `keep` reels ship or the shortlist is exhausted.
        queue = list(ranked)
        while queue and len(result.shipped) < self.cfg.keep:
            need = self.cfg.keep - len(result.shipped)
            wave, queue = queue[:need], queue[need:]
            outcomes = await asyncio.gather(*(self.produce(i) for i in wave), return_exceptions=True)
            for idea, out in zip(wave, outcomes):
                if isinstance(out, Reel):
                    result.shipped.append(out)
                elif isinstance(out, GenerationError):
                    result.rejected.append((idea.working_title, str(out)))
                else:
                    raise out
        result.shipped.sort(key=lambda r: r.virality_score, reverse=True)
        return result
