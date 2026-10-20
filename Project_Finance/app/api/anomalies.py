from __future__ import annotations

from fastapi import APIRouter, Query

from app.analytics.events import track
from app.api.deps import DatasetDep, SessionDep
from app.anomaly.detector import detect_anomalies

router = APIRouter(prefix="/api/anomalies", tags=["anomalies"])


@router.get("/{dataset_id}")
def anomalies(dataset: DatasetDep, session: SessionDep, top_n: int = Query(default=25, ge=1, le=200)):
    report = detect_anomalies(dataset.spending, top_n=top_n)
    track("anomaly_detected", session, anomaly_count=report.flagged_count,
          flag_rate=round(report.flagged_count / max(report.transactions_scanned, 1), 4))
    return report.to_dict()