from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import DatasetDep, SessionDep
from app.anomaly.detector import detect_anomalies
from app.forecasting.model import forecast_dataset
from app.risk.health_score import compute_health_score

router = APIRouter(prefix="/api/insights", tags=["insights"])


@router.get("/{dataset_id}")
def overview(dataset: DatasetDep, session: SessionDep):
    features = dataset.features()
    recurring = dataset.recurring()
    health = compute_health_score(features, recurring)
    forecast = forecast_dataset(dataset.active, features, (30, 60, 90))
    anomalies = detect_anomalies(dataset.spending, top_n=5)

    insights: list[dict] = []

    if recurring.discretionary_annual > 100:
        insights.append({
            "tone": "opportunity",
            "text": f"${recurring.discretionary_annual:,.0f}/yr sits in discretionary recurring charges "
                    f"across {len([s for s in recurring.expenses if s.discretionary and s.active])} "
                    "subscriptions — the most reducible part of your budget.",
        })
    if features.emergency_runway_months >= 3:
        insights.append({
            "tone": "positive",
            "text": f"Emergency reserves cover {features.emergency_runway_months:.1f} months of essential expenses.",
        })
    else:
        insights.append({
            "tone": "warning",
            "text": f"Reserves cover only {features.emergency_runway_months:.1f} months of essentials; "
                    "three months is the usual first milestone.",
        })
    if features.trend_slope_monthly < -50:
        insights.append({
            "tone": "warning",
            "text": f"Monthly net cash flow is trending down by about "
                    f"${abs(features.trend_slope_monthly):,.0f} per month.",
        })
    if anomalies.flagged_count:
        insights.append({
            "tone": "warning",
            "text": f"{anomalies.flagged_count} transaction(s) fall well outside your own spending baselines.",
        })
    review = int((dataset.df["category"] == "Needs Review").sum())
    if review:
        insights.append({
            "tone": "action",
            "text": f"{review} transaction(s) could not be categorised confidently — "
                    "confirming them improves every downstream number.",
        })

    return {
        "dataset_id": dataset.dataset_id,
        "headline": {
            "health_score": round(health.score, 1),
            "band": health.explanation.band,
            "balance": round(features.liquid_savings, 2),
            "balance_source": features.balance_source,
            "monthly_net": round(features.net_monthly_mean, 2),
            "monthly_income": round(features.monthly_income_mean, 2),
            "dti": round(
                features.debt_service_monthly / features.monthly_income_mean, 4
            ) if features.monthly_income_mean else None,
            "runway_months": round(features.emergency_runway_months, 2),
            "savings_rate": round(features.savings_rate, 4),
        },
        "health": health.to_dict(),
        "forecast": forecast.to_dict(),
        "recurring": recurring.to_dict()["summary"],
        "top_categories": [
            {"category": k, "monthly": round(v, 2)}
            for k, v in list(features.category_monthly.items())[:8]
        ],
        "anomalies": [a.to_dict() for a in anomalies.anomalies],
        "insights": insights,
        "warnings": features.warnings,
    }