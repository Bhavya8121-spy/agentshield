from __future__ import annotations

from fastapi import APIRouter

from app.analytics.metrics import usage_summary
from app.categorization.feedback import stats

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/summary")
def summary():
    return usage_summary()


@router.get("/feedback")
def feedback():
    return stats()