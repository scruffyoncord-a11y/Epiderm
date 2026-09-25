"""One risk summary for every check: a 0-100 risk score, its inverse (the security score), a plain verdict, a
breakdown by area, and a likelihood x impact risk matrix.

The score never contradicts the verdict band the rules set: it is placed inside that band's range, so an
"allow" result can never show a higher risk than a "verify" one. Inside a band it rises with the combined
weight of the suspicious signals (noisy-OR of strength x confidence), so more and stronger evidence moves it
up. Reassuring signals are listed but never lower it, in keeping with "the model can never lower a verdict".
"""
from __future__ import annotations

import math
from typing import Iterable, Optional

from .models import Band, Direction, RiskArea, RiskFactor, RiskPart, RiskSummary, Signal

# Where each band's score may fall. The gaps make the three verdicts visibly different.
BAND_RANGE = {Band.allow: (3, 30), Band.step_up: (38, 68), Band.verify: (72, 99)}
BAND_ORDER = [Band.allow, Band.step_up, Band.verify]
VERDICT = {
    Band.allow: ("legit", "LOOKS LEGIT"),
    Band.step_up: ("suspicious", "SUSPICIOUS"),
    Band.verify: ("not_legit", "NOT LEGIT"),
}

# Signal id prefix -> the area it belongs to in the breakdown
AREAS = [
    ("text.", "Wording & tactics"),
    ("email.", "Sender & headers"),
    ("url.", "Links"),
    ("document.", "File metadata"),
    ("content.", "Document contents"),
]
OTHER_AREA = "Other"


def area_of(signal_id: str) -> str:
    return next((name for prefix, name in AREAS if signal_id.startswith(prefix)), OTHER_AREA)


def _bucket(x: float) -> int:
    return min(5, max(1, math.ceil(x * 5 - 1e-9)))


def _noisy_or(weights: Iterable[float]) -> float:
    p = 1.0
    for w in weights:
        p *= 1.0 - max(0.0, min(1.0, w))
    return 1.0 - p


def _level(score: int) -> str:
    return "low" if score <= 30 else "medium" if score <= 55 else "high" if score <= 80 else "critical"


def summarise(signals: list[Signal], band: Band, source: str = "") -> RiskSummary:
    sus = [s for s in signals if s.direction == Direction.suspicious]
    raw = _noisy_or(s.strength * s.confidence for s in sus)
    lo, hi = BAND_RANGE[band]
    score = round(lo + raw * (hi - lo))

    areas: dict[str, RiskArea] = {}
    for s in signals:
        a = areas.setdefault(area_of(s.id), RiskArea(name=area_of(s.id), risk=0))
        if s.direction == Direction.suspicious:
            a.suspicious += 1
        elif s.direction == Direction.reassuring:
            a.reassuring += 1
        elif s.direction == Direction.unknown:
            a.unknown += 1
    for name, a in areas.items():
        a.risk = round(100 * _noisy_or(s.strength * s.confidence for s in sus if area_of(s.id) == name))

    matrix = sorted(
        (RiskFactor(id=s.id, label=s.finding, area=area_of(s.id), likelihood=_bucket(s.confidence), impact=_bucket(s.strength),
                    weight=round(100 * s.strength * s.confidence), source=source) for s in sus),
        key=lambda f: -f.weight)
    verdict, label = VERDICT[band]
    return RiskSummary(
        risk_score=score, security_score=100 - score, verdict=verdict, verdict_label=label, level=_level(score), band=band,
        areas=sorted(areas.values(), key=lambda a: -a.risk), matrix=matrix, suspicious=len(sus),
        reassuring=sum(s.direction == Direction.reassuring for s in signals),
        unknown=sum(s.direction == Direction.unknown for s in signals),
        basis="The verdict comes from the rules. The score sits inside that verdict's range and rises with the combined "
              "weight (strength x confidence) of the warning signs. Reassuring signs are shown but never lower it.")


def combine(parts: list[tuple[str, RiskSummary]]) -> Optional[RiskSummary]:
    """Several things checked together (a message and its attachment): the worst verdict wins, and the score is
    the highest of the parts, raised a little for each other part that is itself a warning."""
    parts = [(n, p) for n, p in parts if p is not None]
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0][1]
    band = max((p.band for _, p in parts), key=BAND_ORDER.index)
    lo, hi = BAND_RANGE[band]
    top = max(p.risk_score for _, p in parts)
    extra = sum(4 for _, p in parts if p.band != Band.allow) - (4 if band != Band.allow else 0)
    score = max(lo, min(hi, top + extra))

    areas: dict[str, RiskArea] = {}
    for _, p in parts:
        for a in p.areas:
            cur = areas.get(a.name)
            if cur is None:
                areas[a.name] = a.model_copy()
            else:
                cur.risk = max(cur.risk, a.risk)
                cur.suspicious += a.suspicious
                cur.reassuring += a.reassuring
                cur.unknown += a.unknown
    verdict, label = VERDICT[band]
    return RiskSummary(
        risk_score=score, security_score=100 - score, verdict=verdict, verdict_label=label, level=_level(score), band=band,
        areas=sorted(areas.values(), key=lambda a: -a.risk),
        matrix=sorted((f for _, p in parts for f in p.matrix), key=lambda f: -f.weight),
        suspicious=sum(p.suspicious for _, p in parts), reassuring=sum(p.reassuring for _, p in parts),
        unknown=sum(p.unknown for _, p in parts),
        parts=[RiskPart(name=n, risk_score=p.risk_score, verdict=p.verdict) for n, p in parts],
        basis="The worst verdict of the items checked is the overall verdict. " + parts[0][1].basis)
