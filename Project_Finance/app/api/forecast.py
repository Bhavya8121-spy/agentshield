from __future__ import annotations

from fastapi import APIRouter, Query

from app.analytics.events import track
from app.api.deps import DatasetDep, SessionDep, Timer
from app.forecasting.backtest import backtest_summary_markdown, walk_forward
from app.forecasting.model import forecast_dataset

router = APIRouter(prefix="/api/forecast", tags=["forecast"])


@router.get("/{dataset_id}")
def forecast(
    dataset: DatasetDep,
    session: SessionDep,
    days: list[int] = Query(default=[30, 60, 90]),
    confidence: float = Query(default=0.80, ge=0.5, le=0.95),
):
    horizons = tuple(sorted({d for d in days if 1 <= d <= 730})) or (30, 60, 90)
    with Timer() as timer:
        result = forecast_dataset(dataset.active, dataset.features(), horizons, confidence)
    track("forecast_generated", session, horizon_days=max(horizons), duration_ms=timer.elapsed_ms)
    return result.to_dict()


@router.get("/{dataset_id}/backtest")
def backtest(
    dataset: DatasetDep,
    session: SessionDep,
    confidence: float = Query(default=0.80, ge=0.5, le=0.95),
):
    with Timer() as timer:
        report = walk_forward(dataset.active, confidence=confidence)
    track("backtest_run", session, duration_ms=timer.elapsed_ms)
    return {**report.to_dict(), "markdown": backtest_summary_markdown(report)}