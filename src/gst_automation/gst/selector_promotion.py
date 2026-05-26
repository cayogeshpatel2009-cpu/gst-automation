from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gst_automation.core.logging import get_logger
from gst_automation.core.settings import Settings
from gst_automation.db.models.gst.observation import GstObservationSession
from gst_automation.db.models.portal.selector_def import PortalSelectorDef
from gst_automation.portal.selectors.types import SelectorCandidate, SelectorDefinition


logger = get_logger(__name__)


_DYNAMIC_ID = re.compile(r"#?[A-Za-z_-]*\\d{3,}[A-Za-z_-]*")


@dataclass(frozen=True, slots=True)
class SelectorScore:
    score: int
    reasons: list[str]


def score_css_selector(sel: str) -> SelectorScore:
    score = 100
    reasons: list[str] = []
    if "nth-child" in sel or "nth-of-type" in sel:
        score -= 25
        reasons.append("nth_child")
    if _DYNAMIC_ID.search(sel):
        score -= 30
        reasons.append("dynamic_id_like")
    if sel.count(">") >= 3:
        score -= 10
        reasons.append("deep_chain")
    if "[class" in sel or ".css-" in sel:
        score -= 10
        reasons.append("class_dependent")
    if " " in sel:
        score -= 5
        reasons.append("descendant_selector")
    return SelectorScore(score=max(0, min(100, score)), reasons=reasons)


@dataclass(frozen=True, slots=True)
class ObservedSelector:
    selector: str
    count: int
    score: int
    reasons: list[str]


@dataclass(frozen=True, slots=True)
class SelectorPromotionService:
    settings: Settings

    async def list_observed(self, session: AsyncSession, *, observation_id: uuid.UUID) -> list[ObservedSelector]:
        obs = await session.get(GstObservationSession, observation_id)
        if obs is None:
            raise RuntimeError("observation not found")
        selectors_path = (
            Path(self.settings.browser_artifacts_dir)
            / str(obs.job_id)
            / str(obs.context_id)
            / "gst_selectors"
            / "selectors_observed.json"
        )
        if not selectors_path.exists():
            return []
        raw = json.loads(selectors_path.read_text(encoding="utf-8"))
        out: list[ObservedSelector] = []
        for sel, cnt in raw.items():
            if not isinstance(sel, str):
                continue
            if not isinstance(cnt, int):
                try:
                    cnt = int(cnt)
                except Exception:
                    cnt = 0
            sc = score_css_selector(sel)
            out.append(ObservedSelector(selector=sel, count=cnt, score=sc.score, reasons=sc.reasons))
        out.sort(key=lambda x: (x.score, x.count), reverse=True)
        return out

    async def promote(
        self,
        session: AsyncSession,
        *,
        semantic_key: str,
        selectors: list[str],
        activate: bool,
    ) -> uuid.UUID:
        key = semantic_key.strip()
        if not key or len(key) > 128:
            raise ValueError("invalid semantic_key")
        candidates: list[SelectorCandidate] = []
        for s in selectors:
            s = s.strip()
            if not s:
                continue
            sc = score_css_selector(s)
            candidates.append(SelectorCandidate(kind="css", value=s, weight=sc.score))
        if not candidates:
            raise ValueError("no selectors provided")

        res = await session.execute(select(PortalSelectorDef.version).where(PortalSelectorDef.key == key))
        versions = [int(r[0]) for r in res.all()]
        next_version = (max(versions) + 1) if versions else 1

        row = PortalSelectorDef(
            key=key,
            version=next_version,
            candidates_json=json.dumps(
                {
                    "candidates": [{"kind": c.kind, "value": c.value, "weight": c.weight} for c in candidates],
                    "source": "observation_promotion",
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            active=1 if activate else 0,
        )
        session.add(row)
        await session.flush()
        logger.info("gst.selector_promoted", key=key, version=next_version, active=bool(row.active))
        return row.id


@dataclass(frozen=True, slots=True)
class SelectorRegistryLoader:
    async def load_active_prefix(
        self, session: AsyncSession, *, prefix: str
    ) -> dict[tuple[str, int], SelectorDefinition]:
        res = await session.execute(
            select(PortalSelectorDef).where(PortalSelectorDef.key.like(f"{prefix}%")).where(PortalSelectorDef.active == 1)
        )
        defs: dict[tuple[str, int], SelectorDefinition] = {}
        for row in res.scalars().all():
            try:
                obj = json.loads(row.candidates_json)
                raw = obj.get("candidates", [])
                candidates = []
                for c in raw:
                    if isinstance(c, str):
                        candidates.append(SelectorCandidate(kind="css", value=c, weight=100))
                    elif isinstance(c, dict):
                        candidates.append(
                            SelectorCandidate(
                                kind=str(c.get("kind") or "css"),  # type: ignore[arg-type]
                                value=str(c.get("value") or ""),
                                weight=int(c.get("weight") or 100),
                            )
                        )
                candidates_t = tuple([c for c in candidates if c.value])
                defs[(row.key, int(row.version))] = SelectorDefinition(
                    key=row.key, version=int(row.version), candidates=candidates_t
                )
            except Exception:
                continue
        return defs

