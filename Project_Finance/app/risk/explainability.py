from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Factor:
    """One scored dimension and its contribution to the headline number."""

    key: str
    label: str
    value: float
    display: str
    score: float               # 0..100 for this dimension
    weight: float              # share of the headline score
    points_earned: float
    points_possible: float
    direction: str             # positive | negative | neutral
    detail: str = ""

    @property
    def points_lost(self) -> float:
        return round(self.points_possible - self.points_earned, 1)

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["points_lost"] = self.points_lost
        for key in ("value", "score", "points_earned", "points_possible"):
            payload[key] = round(payload[key], 2)
        return payload


@dataclass
class Explanation:
    score: float
    band: str
    factors: list[Factor] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    deductions: list[dict] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "score": round(self.score, 1),
            "band": self.band,
            "factors": [f.to_dict() for f in self.factors],
            "strengths": self.strengths,
            "risks": self.risks,
            "deductions": self.deductions,
            "assumptions": self.assumptions,
        }


POSITIVE_THRESHOLD = 75.0
NEGATIVE_THRESHOLD = 50.0


def classify_factor(score: float) -> str:
    if score >= POSITIVE_THRESHOLD:
        return "positive"
    if score < NEGATIVE_THRESHOLD:
        return "negative"
    return "neutral"


def build_explanation(score: float, factors: list[Factor], bands: list[tuple[float, str]],
                      assumptions: list[str] | None = None) -> Explanation:
    explanation = Explanation(score=score, band=band_for(score, bands), factors=factors,
                              assumptions=assumptions or [])
    for factor in sorted(factors, key=lambda f: -f.points_lost):
        line = f"{factor.label}: {factor.display}"
        if factor.detail:
            line += f" — {factor.detail}"
        if factor.direction == "positive":
            explanation.strengths.append(line)
        elif factor.direction == "negative":
            explanation.risks.append(line)
        if factor.points_lost >= 0.5:
            explanation.deductions.append({
                "points": -factor.points_lost,
                "reason": f"{factor.label} ({factor.display})",
                "key": factor.key,
            })
    return explanation


def band_for(score: float, bands: list[tuple[float, str]]) -> str:
    for floor, label in bands:
        if score >= floor:
            return label
    return bands[-1][1]


def linear_score(value: float, worst: float, best: float) -> float:
    """Map a value onto 0..100, handling inverted scales (worst > best)."""
    if worst == best:
        return 100.0
    ratio = (value - worst) / (best - worst)
    return float(max(0.0, min(1.0, ratio)) * 100.0)