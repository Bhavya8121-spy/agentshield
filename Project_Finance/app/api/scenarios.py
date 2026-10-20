from __future__ import annotations

from fastapi import APIRouter

from app.analytics.events import track
from app.api.deps import DatasetDep, SessionDep, Timer
from app.core.exceptions import ValidationFailure
from app.simulation.monte_carlo import MonteCarloRequest, run_monte_carlo
from app.simulation.stress_test import PRESETS, ScenarioSpec, run_all_presets, run_stress_test

router = APIRouter(prefix="/api/simulation", tags=["simulation"])


@router.get("/presets")
def presets():
    return {"presets": [spec.model_dump() for spec in PRESETS.values()]}


@router.post("/{dataset_id}/monte-carlo")
def monte_carlo(dataset: DatasetDep, body: MonteCarloRequest, session: SessionDep):
    with Timer() as timer:
        result = run_monte_carlo(dataset.features(), dataset.recurring(), body)
    track("monte_carlo_completed", session, runs=body.runs, duration_ms=timer.elapsed_ms)
    return result.to_dict()


@router.post("/{dataset_id}/stress-test")
def stress_test(dataset: DatasetDep, body: ScenarioSpec, session: SessionDep):
    spec = body
    if body.key in PRESETS and body.label == ScenarioSpec().label:
        spec = PRESETS[body.key].model_copy(update={"horizon_months": body.horizon_months})
    result = run_stress_test(dataset.features(), spec, dataset.recurring())
    track("stress_test_completed", session, scenario=spec.key)
    return result.to_dict()


@router.get("/{dataset_id}/stress-test/all")
def stress_all(dataset: DatasetDep, session: SessionDep):
    track("stress_test_completed", session, scenario="all_presets")
    return {"scenarios": run_all_presets(dataset.features(), dataset.recurring())}


@router.post("/{dataset_id}/stress-test/preset/{key}")
def stress_preset(dataset: DatasetDep, key: str, session: SessionDep, horizon_months: int = 12):
    if key not in PRESETS:
        raise ValidationFailure(f"Unknown preset '{key}'.", {"available": list(PRESETS)})
    spec = PRESETS[key].model_copy(update={"horizon_months": horizon_months})
    result = run_stress_test(dataset.features(), spec, dataset.recurring())
    track("stress_test_completed", session, scenario=key)
    return result.to_dict()