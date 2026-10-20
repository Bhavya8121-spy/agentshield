from __future__ import annotations

from fastapi import APIRouter

from app.analytics.events import track
from app.api.deps import DatasetDep, SessionDep
from app.risk.affordability import AffordabilityRequest, evaluate_affordability
from app.risk.health_score import compute_health_score

router = APIRouter(prefix="/api/risk", tags=["risk"])


@router.post("/{dataset_id}/affordability")
def affordability(dataset: DatasetDep, body: AffordabilityRequest, session: SessionDep):
    result = evaluate_affordability(dataset.features(), body)
    track("affordability_calculated", session, score_band=result.explanation.band)
    return result.to_dict()


@router.get("/{dataset_id}/health")
def health(dataset: DatasetDep, session: SessionDep):
    score = compute_health_score(dataset.features(), dataset.recurring())
    track("health_score_viewed", session, score_band=score.explanation.band)
    return score.to_dict()